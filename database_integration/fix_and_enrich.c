/*
 * Fix encoding issues and enrich SQLite database:
 * - Fix double UTF-8 encoding (UTF-8 interpreted as Latin-1, then re-encoded)
 * - Clean dates (remove T00:00:00Z suffix)
 * - Add count columns to lookup tables (occupations, cities)
 * - Add nationalities table with counts
 *
 * Compile: gcc -O3 -o fix_and_enrich fix_and_enrich.c -lsqlite3
 * Run: ./fix_and_enrich ../data/all_humans/humans_clean.sqlite3 ../data/all_humans/humans_final.sqlite3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sqlite3.h>
#include <time.h>

#define BATCH_SIZE 50000
#define MAX_STRING 65536

/*
 * Fix double UTF-8 encoding.
 * When UTF-8 bytes are interpreted as Latin-1 and re-encoded to UTF-8:
 *   "ü" (C3 BC) -> "Ã¼" (C3 83 C2 BC)
 *
 * Fix: decode UTF-8 chars to their codepoints, if all < 256,
 * treat those as Latin-1 bytes and interpret as UTF-8.
 */

/* Check if a byte sequence is valid UTF-8 */
static int is_valid_utf8(const unsigned char* s, size_t len) {
    size_t i = 0;
    while (i < len) {
        if (s[i] < 0x80) {
            i++;
        } else if ((s[i] & 0xE0) == 0xC0) {
            if (i + 1 >= len || (s[i+1] & 0xC0) != 0x80) return 0;
            if (s[i] < 0xC2) return 0; /* overlong */
            i += 2;
        } else if ((s[i] & 0xF0) == 0xE0) {
            if (i + 2 >= len || (s[i+1] & 0xC0) != 0x80 || (s[i+2] & 0xC0) != 0x80) return 0;
            i += 3;
        } else if ((s[i] & 0xF8) == 0xF0) {
            if (i + 3 >= len || (s[i+1] & 0xC0) != 0x80 || (s[i+2] & 0xC0) != 0x80 || (s[i+3] & 0xC0) != 0x80) return 0;
            i += 4;
        } else {
            return 0;
        }
    }
    return 1;
}

/* Check if string likely has double encoding (contains suspicious patterns) */
static int has_double_encoding(const char* s) {
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        /* Look for Ã (C3 83) which is U+00C3 - common in double-encoded text */
        if (p[0] == 0xC3 && p[1] == 0x83) return 1;
        /* Look for Â (C2 82-BF) which is U+00C2 */
        if (p[0] == 0xC2 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        /* Look for â (E2 80 xx) - often double-encoded dashes/quotes */
        if (p[0] == 0xC3 && p[1] == 0xA2) return 1;
        p++;
    }
    return 0;
}

/* Fix double UTF-8 encoding */
static int fix_double_utf8(const char* input, char* output, size_t max_len) {
    if (!input || !*input) {
        output[0] = '\0';
        return 0;
    }

    /* Quick check: if no suspicious patterns, just copy */
    if (!has_double_encoding(input)) {
        strncpy(output, input, max_len - 1);
        output[max_len - 1] = '\0';
        return 0;
    }

    /* Phase 1: Decode UTF-8 to codepoints, store as bytes if < 256 */
    unsigned char temp[MAX_STRING];
    size_t temp_len = 0;
    const unsigned char* p = (const unsigned char*)input;

    while (*p && temp_len < sizeof(temp) - 1) {
        uint32_t cp;
        int skip;

        if ((*p & 0x80) == 0) {
            /* ASCII */
            cp = *p;
            skip = 1;
        } else if ((*p & 0xE0) == 0xC0 && (p[1] & 0xC0) == 0x80) {
            /* 2-byte UTF-8 */
            cp = ((*p & 0x1F) << 6) | (p[1] & 0x3F);
            skip = 2;
        } else if ((*p & 0xF0) == 0xE0 && (p[1] & 0xC0) == 0x80 && (p[2] & 0xC0) == 0x80) {
            /* 3-byte UTF-8 */
            cp = ((*p & 0x0F) << 12) | ((p[1] & 0x3F) << 6) | (p[2] & 0x3F);
            skip = 3;
        } else if ((*p & 0xF8) == 0xF0 && (p[1] & 0xC0) == 0x80 && (p[2] & 0xC0) == 0x80 && (p[3] & 0xC0) == 0x80) {
            /* 4-byte UTF-8 */
            cp = ((*p & 0x07) << 18) | ((p[1] & 0x3F) << 12) | ((p[2] & 0x3F) << 6) | (p[3] & 0x3F);
            skip = 4;
        } else {
            /* Invalid UTF-8 byte, copy as-is */
            temp[temp_len++] = *p++;
            continue;
        }

        if (cp < 256) {
            /* Fits in a byte - could be from double-encoding */
            temp[temp_len++] = (unsigned char)cp;
        } else {
            /* Codepoint > 255: not double-encoded, abort and return original */
            strncpy(output, input, max_len - 1);
            output[max_len - 1] = '\0';
            return 0;
        }
        p += skip;
    }
    temp[temp_len] = '\0';

    /* Phase 2: Check if temp is valid UTF-8 */
    if (is_valid_utf8(temp, temp_len)) {
        memcpy(output, temp, temp_len + 1);
        return 1; /* Fixed */
    } else {
        /* Not valid UTF-8 after fix attempt, return original */
        strncpy(output, input, max_len - 1);
        output[max_len - 1] = '\0';
        return 0;
    }
}

/* Clean date: remove T00:00:00Z suffix */
static void clean_date(const char* input, char* output, size_t max_len) {
    if (!input || !*input) {
        output[0] = '\0';
        return;
    }

    strncpy(output, input, max_len - 1);
    output[max_len - 1] = '\0';

    /* Find and remove T00:00:00Z */
    char* t = strstr(output, "T00:00:00Z");
    if (t) {
        *t = '\0';
    }

    /* Also handle T00:00:00 without Z */
    t = strstr(output, "T00:00:00");
    if (t) {
        *t = '\0';
    }
}

/* Process string: fix encoding, also clean @en tags and quotes */
static void process_string(const char* input, char* output, size_t max_len) {
    if (!input || !*input) {
        output[0] = '\0';
        return;
    }

    /* First fix encoding */
    char temp[MAX_STRING];
    fix_double_utf8(input, temp, sizeof(temp));

    /* Then clean quotes and @en tags */
    size_t j = 0;
    size_t len = strlen(temp);

    for (size_t i = 0; i < len && j < max_len - 1; i++) {
        /* Skip double quotes */
        if (temp[i] == '"') continue;

        /* Skip @en at end */
        if (i + 3 <= len && temp[i] == '@' && temp[i+1] == 'e' && temp[i+2] == 'n') {
            if (i + 3 == len || temp[i+3] == ';' || temp[i+3] == ' ') {
                i += 2;
                continue;
            }
        }
        output[j++] = temp[i];
    }
    output[j] = '\0';

    /* Trim */
    while (j > 0 && (output[j-1] == ' ' || output[j-1] == ';')) {
        output[--j] = '\0';
    }
    char* start = output;
    while (*start == ' ') start++;
    if (start != output) {
        memmove(output, start, strlen(start) + 1);
    }
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input.sqlite3> <output.sqlite3>\n", argv[0]);
        return 1;
    }

    const char* input_path = argv[1];
    const char* output_path = argv[2];

    sqlite3 *db_in, *db_out;
    sqlite3_stmt *stmt_read, *stmt_write;
    int rc;

    printf("============================================================\n");
    printf("FIX ENCODING & ENRICH DATABASE\n");
    printf("============================================================\n\n");
    fflush(stdout);

    /* Open input database */
    printf("[1/7] Opening input database...\n");
    fflush(stdout);
    rc = sqlite3_open_v2(input_path, &db_in, SQLITE_OPEN_READONLY, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open input: %s\n", sqlite3_errmsg(db_in));
        return 1;
    }
    printf("  ✓ Opened %s\n", input_path);

    /* Create output database */
    remove(output_path);
    printf("\n[2/7] Creating output database...\n");
    rc = sqlite3_open(output_path, &db_out);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot create output: %s\n", sqlite3_errmsg(db_out));
        return 1;
    }

    /* Optimize for speed */
    sqlite3_exec(db_out, "PRAGMA synchronous = OFF", NULL, NULL, NULL);
    sqlite3_exec(db_out, "PRAGMA journal_mode = MEMORY", NULL, NULL, NULL);
    sqlite3_exec(db_out, "PRAGMA cache_size = 1000000", NULL, NULL, NULL);

    /* Create schema */
    const char* create_sql =
        "CREATE TABLE individuals ("
        "  wikidata_id TEXT PRIMARY KEY,"
        "  name_en TEXT,"
        "  description_en TEXT,"
        "  birthdate TEXT,"
        "  deathdate TEXT,"
        "  nationalities_en TEXT,"
        "  birthcity_en TEXT,"
        "  deathcity_en TEXT,"
        "  occupations_en TEXT"
        ");"
        "CREATE TABLE occupations ("
        "  id TEXT PRIMARY KEY,"
        "  name_en TEXT,"
        "  count INTEGER DEFAULT 0"
        ");"
        "CREATE TABLE cities ("
        "  id TEXT PRIMARY KEY,"
        "  name_en TEXT,"
        "  count INTEGER DEFAULT 0"
        ");"
        "CREATE TABLE nationalities ("
        "  name_en TEXT PRIMARY KEY,"
        "  count INTEGER DEFAULT 0"
        ");";

    rc = sqlite3_exec(db_out, create_sql, NULL, NULL, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot create schema: %s\n", sqlite3_errmsg(db_out));
        return 1;
    }
    printf("  ✓ Schema created with count columns\n");

    /* Process individuals */
    printf("\n[3/7] Processing individuals (fixing encoding + cleaning dates)...\n");
    fflush(stdout);
    clock_t start = clock();

    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    const char* select_sql = "SELECT wikidata_id, name_en, description_en, birthdate, deathdate, "
                             "nationalities_en, birthcity_en, deathcity_en, occupations_en FROM individuals";
    rc = sqlite3_prepare_v2(db_in, select_sql, -1, &stmt_read, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot prepare select: %s\n", sqlite3_errmsg(db_in));
        return 1;
    }

    const char* insert_sql = "INSERT INTO individuals VALUES (?,?,?,?,?,?,?,?,?)";
    rc = sqlite3_prepare_v2(db_out, insert_sql, -1, &stmt_write, NULL);

    char buffer[MAX_STRING];
    char date_buffer[256];
    long count = 0;
    long fixed_count = 0;

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        /* wikidata_id */
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);

        /* Text columns: fix encoding */
        for (int i = 1; i <= 2; i++) { /* name, description */
            const char* val = (const char*)sqlite3_column_text(stmt_read, i);
            if (val) {
                int was_fixed = fix_double_utf8(val, buffer, sizeof(buffer));
                if (was_fixed) fixed_count++;
                process_string(val, buffer, sizeof(buffer));
                sqlite3_bind_text(stmt_write, i + 1, buffer[0] ? buffer : NULL, -1, SQLITE_TRANSIENT);
            } else {
                sqlite3_bind_null(stmt_write, i + 1);
            }
        }

        /* Date columns: clean format */
        for (int i = 3; i <= 4; i++) { /* birthdate, deathdate */
            const char* val = (const char*)sqlite3_column_text(stmt_read, i);
            if (val) {
                clean_date(val, date_buffer, sizeof(date_buffer));
                sqlite3_bind_text(stmt_write, i + 1, date_buffer[0] ? date_buffer : NULL, -1, SQLITE_TRANSIENT);
            } else {
                sqlite3_bind_null(stmt_write, i + 1);
            }
        }

        /* Remaining text columns */
        for (int i = 5; i <= 8; i++) { /* nationalities, birthcity, deathcity, occupations */
            const char* val = (const char*)sqlite3_column_text(stmt_read, i);
            if (val) {
                process_string(val, buffer, sizeof(buffer));
                sqlite3_bind_text(stmt_write, i + 1, buffer[0] ? buffer : NULL, -1, SQLITE_TRANSIENT);
            } else {
                sqlite3_bind_null(stmt_write, i + 1);
            }
        }

        sqlite3_step(stmt_write);
        sqlite3_reset(stmt_write);

        count++;
        if (count % 100000 == 0) {
            printf("\r  %ld rows processed...", count);
            fflush(stdout);
        }
        if (count % BATCH_SIZE == 0) {
            sqlite3_exec(db_out, "COMMIT", NULL, NULL, NULL);
            sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);
        }
    }

    sqlite3_exec(db_out, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt_read);
    sqlite3_finalize(stmt_write);

    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("\n  ✓ %ld individuals in %.1fs (%ld encoding fixes)\n", count, elapsed, fixed_count);

    /* Process occupations */
    printf("\n[4/7] Processing occupations...\n");
    fflush(stdout);
    start = clock();

    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db_in, "SELECT id, name_en FROM occupations", -1, &stmt_read, NULL);
    rc = sqlite3_prepare_v2(db_out, "INSERT INTO occupations (id, name_en) VALUES (?,?)", -1, &stmt_write, NULL);

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);
        const char* name = (const char*)sqlite3_column_text(stmt_read, 1);
        if (name) {
            process_string(name, buffer, sizeof(buffer));
            sqlite3_bind_text(stmt_write, 2, buffer, -1, SQLITE_TRANSIENT);
        } else {
            sqlite3_bind_null(stmt_write, 2);
        }
        sqlite3_step(stmt_write);
        sqlite3_reset(stmt_write);
    }
    sqlite3_finalize(stmt_read);
    sqlite3_finalize(stmt_write);
    sqlite3_exec(db_out, "COMMIT", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  ✓ Occupations in %.1fs\n", elapsed);

    /* Process cities */
    printf("\n[5/7] Processing cities...\n");
    fflush(stdout);
    start = clock();

    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db_in, "SELECT id, name_en FROM cities", -1, &stmt_read, NULL);
    rc = sqlite3_prepare_v2(db_out, "INSERT INTO cities (id, name_en) VALUES (?,?)", -1, &stmt_write, NULL);

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);
        const char* name = (const char*)sqlite3_column_text(stmt_read, 1);
        if (name) {
            process_string(name, buffer, sizeof(buffer));
            sqlite3_bind_text(stmt_write, 2, buffer, -1, SQLITE_TRANSIENT);
        } else {
            sqlite3_bind_null(stmt_write, 2);
        }
        sqlite3_step(stmt_write);
        sqlite3_reset(stmt_write);
    }
    sqlite3_finalize(stmt_read);
    sqlite3_finalize(stmt_write);
    sqlite3_exec(db_out, "COMMIT", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  ✓ Cities in %.1fs\n", elapsed);

    /* Compute counts */
    printf("\n[6/7] Computing counts...\n");
    fflush(stdout);
    start = clock();

    /* Count occupations - occupations_en contains semicolon-separated IDs */
    printf("  Counting occupations...\n");
    fflush(stdout);
    sqlite3_exec(db_out,
        "UPDATE occupations SET count = ("
        "  SELECT COUNT(*) FROM individuals "
        "  WHERE occupations_en LIKE '%' || occupations.id || '%'"
        ")", NULL, NULL, NULL);

    /* Count cities (birth + death) */
    printf("  Counting cities...\n");
    fflush(stdout);
    sqlite3_exec(db_out,
        "UPDATE cities SET count = ("
        "  SELECT COUNT(*) FROM individuals "
        "  WHERE birthcity_en LIKE '%' || cities.id || '%' "
        "     OR deathcity_en LIKE '%' || cities.id || '%'"
        ")", NULL, NULL, NULL);

    /* Build nationalities table with counts */
    printf("  Building nationalities...\n");
    fflush(stdout);
    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    /* Extract unique nationalities and count them */
    rc = sqlite3_prepare_v2(db_out,
        "SELECT nationalities_en FROM individuals WHERE nationalities_en IS NOT NULL",
        -1, &stmt_read, NULL);
    rc = sqlite3_prepare_v2(db_out,
        "INSERT OR IGNORE INTO nationalities (name_en, count) VALUES (?, 0)",
        -1, &stmt_write, NULL);

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        const char* nats = (const char*)sqlite3_column_text(stmt_read, 0);
        if (nats) {
            /* Split by semicolon */
            char nat_copy[MAX_STRING];
            strncpy(nat_copy, nats, sizeof(nat_copy) - 1);
            nat_copy[sizeof(nat_copy) - 1] = '\0';

            char* token = strtok(nat_copy, ";");
            while (token) {
                /* Trim whitespace */
                while (*token == ' ') token++;
                char* end = token + strlen(token) - 1;
                while (end > token && *end == ' ') *end-- = '\0';

                if (*token) {
                    sqlite3_bind_text(stmt_write, 1, token, -1, SQLITE_TRANSIENT);
                    sqlite3_step(stmt_write);
                    sqlite3_reset(stmt_write);
                }
                token = strtok(NULL, ";");
            }
        }
    }
    sqlite3_finalize(stmt_read);
    sqlite3_finalize(stmt_write);
    sqlite3_exec(db_out, "COMMIT", NULL, NULL, NULL);

    /* Update nationality counts */
    sqlite3_exec(db_out,
        "UPDATE nationalities SET count = ("
        "  SELECT COUNT(*) FROM individuals "
        "  WHERE nationalities_en LIKE '%' || nationalities.name_en || '%'"
        ")", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  ✓ Counts computed in %.1fs\n", elapsed);

    /* Create indexes */
    printf("\n[7/7] Creating indexes...\n");
    fflush(stdout);
    start = clock();

    sqlite3_exec(db_out, "CREATE INDEX idx_name ON individuals(name_en)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_birthcity ON individuals(birthcity_en)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_birthdate ON individuals(birthdate)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_occ_count ON occupations(count DESC)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_city_count ON cities(count DESC)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_nat_count ON nationalities(count DESC)", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  ✓ Indexes in %.1fs\n", elapsed);

    /* Close */
    sqlite3_close(db_in);
    sqlite3_close(db_out);

    printf("\n============================================================\n");
    printf("DONE!\n");
    printf("Output: %s\n", output_path);
    printf("============================================================\n");

    return 0;
}
