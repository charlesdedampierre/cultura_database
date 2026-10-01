/*
 * Enhance SQLite database with additional data from JSON files.
 *
 * Adds:
 * - sitelinks_count column to individuals
 * - lat, lon, country_id, country_name to cities table
 * - nationalities table with country info
 * - meta_occupation column to occupations (scientist/artist)
 *
 * Compile: gcc -O3 -o enhance_sqlite enhance_sqlite.c -lsqlite3
 * Run: ./enhance_sqlite ../data/all_humans/humans_clean.sqlite3 ../data/all_humans
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <time.h>
#include <ctype.h>

#define BATCH_SIZE 50000
#define MAX_LINE 1048576  /* 1MB line buffer for large JSON arrays */
#define MAX_ID 32

/* Simple JSON string extraction - finds value for a key */
static char* extract_json_string(const char* json, const char* key, char* out, size_t max_len) {
    char search[256];
    snprintf(search, sizeof(search), "\"%s\":", key);
    const char* pos = strstr(json, search);
    if (!pos) {
        out[0] = '\0';
        return out;
    }
    pos += strlen(search);
    while (*pos && isspace(*pos)) pos++;
    if (*pos == '"') {
        pos++;
        size_t i = 0;
        while (*pos && *pos != '"' && i < max_len - 1) {
            if (*pos == '\\' && *(pos+1)) {
                pos++;
            }
            out[i++] = *pos++;
        }
        out[i] = '\0';
    } else {
        out[0] = '\0';
    }
    return out;
}

/* Extract a JSON number */
static double extract_json_number(const char* json, const char* key) {
    char search[256];
    snprintf(search, sizeof(search), "\"%s\":", key);
    const char* pos = strstr(json, search);
    if (!pos) return 0.0;
    pos += strlen(search);
    while (*pos && isspace(*pos)) pos++;
    return atof(pos);
}

/* Count items in a JSON array (counts commas + 1, or 0 if empty) */
static int count_json_array(const char* json) {
    if (!json) return 0;
    const char* start = strchr(json, '[');
    if (!start) return 0;
    start++;
    while (*start && isspace(*start)) start++;
    if (*start == ']') return 0;

    int count = 1;
    int depth = 0;
    int in_string = 0;

    for (const char* p = start; *p && !(*p == ']' && depth == 0); p++) {
        if (*p == '\\' && in_string) {
            p++;
            continue;
        }
        if (*p == '"') in_string = !in_string;
        if (!in_string) {
            if (*p == '[' || *p == '{') depth++;
            else if (*p == ']' || *p == '}') depth--;
            else if (*p == ',' && depth == 0) count++;
        }
    }
    return count;
}

/* Progress bar */
static void print_progress(long current, long total, clock_t start) {
    int bar_width = 40;
    double progress = (double)current / total;
    int filled = (int)(bar_width * progress);
    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    double rate = current / (elapsed > 0 ? elapsed : 1);

    printf("\r  [");
    for (int i = 0; i < bar_width; i++) {
        printf(i < filled ? "=" : " ");
    }
    printf("] %5.1f%% (%ld/%ld) %.0f/s", progress * 100, current, total, rate);
    fflush(stdout);
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <database.sqlite3> <data_dir>\n", argv[0]);
        return 1;
    }

    const char* db_path = argv[1];
    const char* data_dir = argv[2];
    char filepath[1024];

    sqlite3 *db;
    sqlite3_stmt *stmt;
    int rc;

    printf("============================================================\n");
    printf("ENHANCE SQLITE DATABASE\n");
    printf("============================================================\n\n");

    /* Open database */
    printf("[1/6] Opening database...\n");
    rc = sqlite3_open(db_path, &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        return 1;
    }

    /* Optimize for speed */
    sqlite3_exec(db, "PRAGMA synchronous = OFF", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA journal_mode = MEMORY", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA cache_size = 1000000", NULL, NULL, NULL);
    printf("  Done\n");

    /* ============================================================
     * STEP 2: Add sitelinks_count column (streaming parser for large JSON)
     * ============================================================ */
    printf("\n[2/6] Adding sitelinks_count to individuals...\n");

    /* Add column if not exists */
    rc = sqlite3_exec(db, "ALTER TABLE individuals ADD COLUMN sitelinks_count INTEGER DEFAULT 0", NULL, NULL, NULL);
    if (rc != SQLITE_OK) {
        printf("  Column may already exist, continuing...\n");
    }

    /* Load sitelinks JSON - streaming parser since file is single line 1.2GB */
    snprintf(filepath, sizeof(filepath), "%s/all_human_sitelinks.json", data_dir);
    FILE* f = fopen(filepath, "r");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", filepath);
        return 1;
    }

    /* Get file size for progress */
    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    fseek(f, 0, SEEK_SET);

    clock_t start = clock();
    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db, "UPDATE individuals SET sitelinks_count = ? WHERE wikidata_id = ?", -1, &stmt, NULL);

    char qid[MAX_ID];
    int qid_pos = 0;
    long count = 0;
    long bytes_read = 0;

    /* State machine for streaming JSON parse */
    int in_key = 0;           /* Inside a key string (QID) */
    int in_array = 0;         /* Inside the sitelinks array */
    int in_url_string = 0;    /* Inside a URL string */
    int link_count = 0;       /* Count of URLs in current array */
    int prev_c = 0;

    int c;
    long last_progress = 0;

    while ((c = fgetc(f)) != EOF) {
        bytes_read++;

        if (c == '"' && prev_c != '\\') {
            if (!in_array) {
                /* Toggle key string */
                if (!in_key) {
                    in_key = 1;
                    qid_pos = 0;
                } else {
                    in_key = 0;
                    qid[qid_pos] = '\0';
                }
            } else {
                /* Toggle URL string */
                in_url_string = !in_url_string;
                if (!in_url_string) {
                    /* Just finished reading a URL */
                    link_count++;
                }
            }
        } else if (in_key) {
            /* Accumulate key characters */
            if (qid_pos < MAX_ID - 1) {
                qid[qid_pos++] = c;
            }
        } else if (c == '[' && !in_array) {
            in_array = 1;
            link_count = 0;
        } else if (c == ']' && in_array && !in_url_string) {
            in_array = 0;

            /* Update database with count */
            if (qid[0] == 'Q') {
                sqlite3_bind_int(stmt, 1, link_count);
                sqlite3_bind_text(stmt, 2, qid, -1, SQLITE_TRANSIENT);
                sqlite3_step(stmt);
                sqlite3_reset(stmt);

                count++;

                if (count % BATCH_SIZE == 0) {
                    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
                    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);
                }
            }

            qid[0] = '\0';
        }

        /* Progress every 50MB */
        if (bytes_read - last_progress > 50000000) {
            print_progress(bytes_read, file_size, start);
            last_progress = bytes_read;
        }

        prev_c = c;
    }

    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    fclose(f);

    print_progress(file_size, file_size, start);
    printf("\n  Updated %ld individuals with sitelinks_count\n", count);

    char* line = malloc(MAX_LINE);

    /* ============================================================
     * STEP 3: Update cities with location data
     * ============================================================ */
    printf("\n[3/6] Updating cities with location data...\n");

    /* Add columns if not exist */
    sqlite3_exec(db, "ALTER TABLE cities ADD COLUMN lat REAL", NULL, NULL, NULL);
    sqlite3_exec(db, "ALTER TABLE cities ADD COLUMN lon REAL", NULL, NULL, NULL);
    sqlite3_exec(db, "ALTER TABLE cities ADD COLUMN country_id TEXT", NULL, NULL, NULL);
    sqlite3_exec(db, "ALTER TABLE cities ADD COLUMN country_name TEXT", NULL, NULL, NULL);

    snprintf(filepath, sizeof(filepath), "%s/place_locations.json", data_dir);
    f = fopen(filepath, "r");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", filepath);
        return 1;
    }

    start = clock();
    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db,
        "UPDATE cities SET lat = ?, lon = ?, country_id = ?, country_name = ? WHERE id = ?",
        -1, &stmt, NULL);

    count = 0;
    char name[1024], country_id[MAX_ID], country_name[256];

    while (fgets(line, MAX_LINE, f)) {
        /* Find QID key */
        char* q = strchr(line, 'Q');
        if (!q) continue;

        /* Check if this is a key (followed by ":) */
        char* colon = strchr(q, '"');
        if (!colon || *(colon+1) != ':') continue;

        size_t i = 0;
        while (q[i] && (isalnum(q[i])) && i < MAX_ID - 1) {
            qid[i] = q[i];
            i++;
        }
        qid[i] = '\0';

        /* Read the object - may span multiple lines */
        char obj[4096] = "";
        strncat(obj, line, sizeof(obj) - 1);

        /* Keep reading until we have closing brace */
        while (!strchr(obj, '}') && fgets(line, MAX_LINE, f)) {
            strncat(obj, line, sizeof(obj) - strlen(obj) - 1);
        }

        double lat = extract_json_number(obj, "lat");
        double lon = extract_json_number(obj, "lon");
        extract_json_string(obj, "country_id", country_id, sizeof(country_id));
        extract_json_string(obj, "country_name", country_name, sizeof(country_name));

        sqlite3_bind_double(stmt, 1, lat);
        sqlite3_bind_double(stmt, 2, lon);
        sqlite3_bind_text(stmt, 3, country_id, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 4, country_name, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 5, qid, -1, SQLITE_TRANSIENT);
        sqlite3_step(stmt);
        sqlite3_reset(stmt);

        count++;
        if (count % 10000 == 0) {
            sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
            sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);
            printf("\r  %ld places processed...", count);
            fflush(stdout);
        }
    }

    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    fclose(f);
    printf("\r  Updated %ld places with location data\n", count);

    /* ============================================================
     * STEP 4: Create nationalities table with country info
     * ============================================================ */
    printf("\n[4/6] Creating nationalities table...\n");

    sqlite3_exec(db, "DROP TABLE IF EXISTS nationalities", NULL, NULL, NULL);
    sqlite3_exec(db,
        "CREATE TABLE nationalities ("
        "  id TEXT PRIMARY KEY,"
        "  name_en TEXT,"
        "  country_id TEXT,"
        "  country_name TEXT"
        ")", NULL, NULL, NULL);

    snprintf(filepath, sizeof(filepath), "%s/nationality_countries.json", data_dir);
    f = fopen(filepath, "r");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", filepath);
        return 1;
    }

    start = clock();
    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db,
        "INSERT OR REPLACE INTO nationalities (id, name_en, country_id, country_name) VALUES (?, ?, ?, ?)",
        -1, &stmt, NULL);

    count = 0;

    while (fgets(line, MAX_LINE, f)) {
        char* q = strchr(line, 'Q');
        if (!q) continue;

        char* colon = strchr(q, '"');
        if (!colon || *(colon+1) != ':') continue;

        size_t i = 0;
        while (q[i] && (isalnum(q[i])) && i < MAX_ID - 1) {
            qid[i] = q[i];
            i++;
        }
        qid[i] = '\0';

        char obj[4096] = "";
        strncat(obj, line, sizeof(obj) - 1);
        while (!strchr(obj, '}') && fgets(line, MAX_LINE, f)) {
            strncat(obj, line, sizeof(obj) - strlen(obj) - 1);
        }

        extract_json_string(obj, "name", name, sizeof(name));
        extract_json_string(obj, "country_id", country_id, sizeof(country_id));
        extract_json_string(obj, "country_name", country_name, sizeof(country_name));

        sqlite3_bind_text(stmt, 1, qid, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 2, name, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 3, country_id, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 4, country_name, -1, SQLITE_TRANSIENT);
        sqlite3_step(stmt);
        sqlite3_reset(stmt);

        count++;
    }

    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    fclose(f);
    printf("  Created nationalities table with %ld entries\n", count);

    /* ============================================================
     * STEP 5: Add meta_occupation to occupations table
     * ============================================================ */
    printf("\n[5/6] Adding meta_occupation to occupations...\n");

    sqlite3_exec(db, "ALTER TABLE occupations ADD COLUMN meta_occupation TEXT", NULL, NULL, NULL);

    snprintf(filepath, sizeof(filepath), "%s/suboccupations_scientist_artist.json", data_dir);
    f = fopen(filepath, "r");
    if (!f) {
        fprintf(stderr, "Cannot open %s\n", filepath);
        return 1;
    }

    /* Read entire file */
    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* json_content = malloc(fsize + 1);
    fread(json_content, 1, fsize, f);
    json_content[fsize] = '\0';
    fclose(f);

    start = clock();
    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db,
        "UPDATE occupations SET meta_occupation = ? WHERE id = ?",
        -1, &stmt, NULL);

    /* Process scientist suboccupations */
    const char* scientist_section = strstr(json_content, "\"scientist\"");
    const char* artist_section = strstr(json_content, "\"artist\"");

    long scientist_count = 0, artist_count = 0;

    if (scientist_section) {
        const char* suboccs = strstr(scientist_section, "\"suboccupations\"");
        if (suboccs) {
            const char* end = artist_section ? artist_section : json_content + fsize;
            const char* p = suboccs;

            while (p < end) {
                /* Find QID */
                p = strchr(p, 'Q');
                if (!p || p >= end) break;

                /* Check if it's a key */
                const char* prev = p - 1;
                if (*prev != '"') {
                    p++;
                    continue;
                }

                size_t i = 0;
                while (p[i] && (isalnum(p[i])) && i < MAX_ID - 1) {
                    qid[i] = p[i];
                    i++;
                }
                qid[i] = '\0';

                sqlite3_bind_text(stmt, 1, "scientist", -1, SQLITE_STATIC);
                sqlite3_bind_text(stmt, 2, qid, -1, SQLITE_TRANSIENT);
                sqlite3_step(stmt);
                sqlite3_reset(stmt);

                scientist_count++;
                p += i;
            }
        }
    }

    if (artist_section) {
        const char* suboccs = strstr(artist_section, "\"suboccupations\"");
        if (suboccs) {
            const char* p = suboccs;

            while (*p) {
                p = strchr(p, 'Q');
                if (!p) break;

                const char* prev = p - 1;
                if (*prev != '"') {
                    p++;
                    continue;
                }

                size_t i = 0;
                while (p[i] && (isalnum(p[i])) && i < MAX_ID - 1) {
                    qid[i] = p[i];
                    i++;
                }
                qid[i] = '\0';

                sqlite3_bind_text(stmt, 1, "artist", -1, SQLITE_STATIC);
                sqlite3_bind_text(stmt, 2, qid, -1, SQLITE_TRANSIENT);
                sqlite3_step(stmt);
                sqlite3_reset(stmt);

                artist_count++;
                p += i;
            }
        }
    }

    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    free(json_content);

    printf("  Tagged %ld scientist occupations, %ld artist occupations\n", scientist_count, artist_count);

    /* ============================================================
     * STEP 6: Create indexes
     * ============================================================ */
    printf("\n[6/6] Creating indexes...\n");
    start = clock();

    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_sitelinks ON individuals(sitelinks_count)", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_cities_country ON cities(country_id)", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_nat_country ON nationalities(country_id)", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_occ_meta ON occupations(meta_occupation)", NULL, NULL, NULL);

    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  Indexes created in %.1fs\n", elapsed);

    /* Cleanup */
    free(line);
    sqlite3_close(db);

    printf("\n============================================================\n");
    printf("DONE! Database enhanced: %s\n", db_path);
    printf("============================================================\n");

    return 0;
}
