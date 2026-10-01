/*
 * Add date precision columns to the SQLite database.
 * Reads precision values from JSON and updates the individuals table.
 *
 * Precision values:
 *   11 = day (exact date)
 *   10 = month
 *   9 = year only
 *   8 = decade
 *   7 = century
 *
 * Compile: gcc -O3 -o add_date_precision add_date_precision.c -lsqlite3
 * Run: ./add_date_precision ../data/all_humans/humans_final.sqlite3 ../data/all_humans/all_human_date_precision.json
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <time.h>

#define BATCH_SIZE 50000
#define MAX_LINE 512
#define HASH_SIZE 16000003  /* Prime number for hash table */

/* Hash table entry for precision lookup */
typedef struct PrecisionEntry {
    char* wikidata_id;
    int birthdate_precision;
    int deathdate_precision;
    struct PrecisionEntry* next;
} PrecisionEntry;

/* Hash table */
static PrecisionEntry* hash_table[HASH_SIZE];

/* Simple hash function for Q-ids */
static unsigned int hash_qid(const char* s) {
    unsigned int h = 0;
    while (*s) {
        h = h * 31 + (unsigned char)*s++;
    }
    return h % HASH_SIZE;
}

/* Insert into hash table */
static void hash_insert(const char* qid, int birth_prec, int death_prec) {
    unsigned int idx = hash_qid(qid);
    PrecisionEntry* entry = malloc(sizeof(PrecisionEntry));
    entry->wikidata_id = strdup(qid);
    entry->birthdate_precision = birth_prec;
    entry->deathdate_precision = death_prec;
    entry->next = hash_table[idx];
    hash_table[idx] = entry;
}

/* Lookup in hash table */
static PrecisionEntry* hash_lookup(const char* qid) {
    unsigned int idx = hash_qid(qid);
    PrecisionEntry* entry = hash_table[idx];
    while (entry) {
        if (strcmp(entry->wikidata_id, qid) == 0) {
            return entry;
        }
        entry = entry->next;
    }
    return NULL;
}

/* Free hash table */
static void hash_free(void) {
    for (int i = 0; i < HASH_SIZE; i++) {
        PrecisionEntry* entry = hash_table[i];
        while (entry) {
            PrecisionEntry* next = entry->next;
            free(entry->wikidata_id);
            free(entry);
            entry = next;
        }
    }
}

/* Parse JSON and load into hash table */
static long load_precision_json(const char* json_path) {
    FILE* f = fopen(json_path, "r");
    if (!f) {
        fprintf(stderr, "Cannot open JSON: %s\n", json_path);
        return -1;
    }

    /* Get file size for progress */
    fseek(f, 0, SEEK_END);
    long file_size = ftell(f);
    fseek(f, 0, SEEK_SET);

    long count = 0;
    long bytes_read = 0;
    int last_percent = -1;

    /* Simple state machine JSON parser */
    char qid[64] = {0};
    int birth_prec = -1;
    int death_prec = -1;
    int in_object = 0;
    int in_key = 0;
    int in_value = 0;
    int in_string = 0;
    int awaiting_value = 0;  /* After colon, waiting for value */
    char current_key[64] = {0};
    char current_value[64] = {0};
    int key_pos = 0;
    int val_pos = 0;

    int c;
    while ((c = fgetc(f)) != EOF) {
        bytes_read++;

        /* Progress */
        int percent = (int)((bytes_read * 100) / file_size);
        if (percent != last_percent && percent % 10 == 0) {
            printf("\r  Loading JSON: %d%%...", percent);
            fflush(stdout);
            last_percent = percent;
        }

        if (c == '{') {
            if (in_object == 0) {
                /* Top-level object */
                in_object = 1;
            } else if (in_object == 1) {
                /* Nested object - new entry */
                in_object = 2;
                birth_prec = -1;
                death_prec = -1;
                awaiting_value = 0;
            }
        } else if (c == '}') {
            /* Finish any pending value */
            if (in_value && val_pos > 0) {
                current_value[val_pos] = '\0';
                if (strcmp(current_key, "birthdate_precision") == 0) {
                    if (strcmp(current_value, "null") != 0) {
                        birth_prec = atoi(current_value);
                    }
                } else if (strcmp(current_key, "deathdate_precision") == 0) {
                    if (strcmp(current_value, "null") != 0) {
                        death_prec = atoi(current_value);
                    }
                }
                in_value = 0;
            }
            if (in_object == 2) {
                /* End of nested object - save entry */
                if (qid[0]) {
                    hash_insert(qid, birth_prec, death_prec);
                    count++;
                }
                in_object = 1;
                qid[0] = '\0';
            } else {
                in_object = 0;
            }
        } else if (c == '"') {
            if (!in_string) {
                in_string = 1;
                if (in_object == 1 && !awaiting_value) {
                    /* Starting a key (Q-id) */
                    in_key = 1;
                    key_pos = 0;
                } else if (in_object == 2 && !awaiting_value) {
                    /* Starting a nested key */
                    in_key = 1;
                    key_pos = 0;
                }
            } else {
                in_string = 0;
                if (in_key) {
                    current_key[key_pos] = '\0';
                    if (in_object == 1) {
                        /* This is the Q-id */
                        strcpy(qid, current_key);
                    }
                    in_key = 0;
                }
            }
        } else if (c == ':') {
            if (!in_string) {
                awaiting_value = 1;
                if (in_object == 2) {
                    in_value = 1;
                    val_pos = 0;
                }
            }
        } else if (c == ',') {
            if (!in_string) {
                if (in_value && val_pos > 0) {
                    current_value[val_pos] = '\0';
                    /* Parse the value */
                    if (strcmp(current_key, "birthdate_precision") == 0) {
                        if (strcmp(current_value, "null") != 0) {
                            birth_prec = atoi(current_value);
                        }
                    } else if (strcmp(current_key, "deathdate_precision") == 0) {
                        if (strcmp(current_value, "null") != 0) {
                            death_prec = atoi(current_value);
                        }
                    }
                    in_value = 0;
                }
                awaiting_value = 0;
                current_key[0] = '\0';
            }
        } else if (in_string && in_key && key_pos < 63) {
            current_key[key_pos++] = c;
        } else if (!in_string && in_value && val_pos < 63) {
            if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
                current_value[val_pos++] = c;
            }
        }
    }

    fclose(f);
    printf("\r  Loading JSON: 100%%    \n");
    return count;
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <database.sqlite3> <precision.json>\n", argv[0]);
        return 1;
    }

    const char* db_path = argv[1];
    const char* json_path = argv[2];

    sqlite3 *db;
    sqlite3_stmt *stmt;
    int rc;

    printf("============================================================\n");
    printf("ADD DATE PRECISION TO DATABASE\n");
    printf("============================================================\n\n");
    fflush(stdout);

    /* Load JSON into hash table */
    printf("[1/4] Loading precision data from JSON...\n");
    fflush(stdout);
    clock_t start = clock();

    long json_count = load_precision_json(json_path);
    if (json_count < 0) {
        return 1;
    }

    double elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  Loaded %ld entries in %.1fs\n", json_count, elapsed);

    /* Open database */
    printf("\n[2/4] Opening database...\n");
    fflush(stdout);
    rc = sqlite3_open(db_path, &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        return 1;
    }
    printf("  Opened %s\n", db_path);

    /* Optimize for speed */
    sqlite3_exec(db, "PRAGMA synchronous = OFF", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA journal_mode = MEMORY", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA cache_size = 1000000", NULL, NULL, NULL);

    /* Add columns if they don't exist */
    printf("\n[3/4] Adding precision columns...\n");
    fflush(stdout);

    /* Check if columns exist */
    int has_birth_prec = 0, has_death_prec = 0;
    rc = sqlite3_prepare_v2(db, "PRAGMA table_info(individuals)", -1, &stmt, NULL);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* col_name = (const char*)sqlite3_column_text(stmt, 1);
        if (strcmp(col_name, "birthdate_precision") == 0) has_birth_prec = 1;
        if (strcmp(col_name, "deathdate_precision") == 0) has_death_prec = 1;
    }
    sqlite3_finalize(stmt);

    if (!has_birth_prec) {
        rc = sqlite3_exec(db, "ALTER TABLE individuals ADD COLUMN birthdate_precision INTEGER", NULL, NULL, NULL);
        if (rc != SQLITE_OK) {
            fprintf(stderr, "Cannot add birthdate_precision: %s\n", sqlite3_errmsg(db));
        } else {
            printf("  Added birthdate_precision column\n");
        }
    } else {
        printf("  birthdate_precision column already exists\n");
    }

    if (!has_death_prec) {
        rc = sqlite3_exec(db, "ALTER TABLE individuals ADD COLUMN deathdate_precision INTEGER", NULL, NULL, NULL);
        if (rc != SQLITE_OK) {
            fprintf(stderr, "Cannot add deathdate_precision: %s\n", sqlite3_errmsg(db));
        } else {
            printf("  Added deathdate_precision column\n");
        }
    } else {
        printf("  deathdate_precision column already exists\n");
    }

    /* Update precision values */
    printf("\n[4/4] Updating precision values...\n");
    fflush(stdout);
    start = clock();

    sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);

    /* Prepare update statement */
    rc = sqlite3_prepare_v2(db,
        "UPDATE individuals SET birthdate_precision = ?, deathdate_precision = ? WHERE wikidata_id = ?",
        -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot prepare update: %s\n", sqlite3_errmsg(db));
        return 1;
    }

    /* Iterate through hash table and update */
    long updated = 0;
    long batch_count = 0;

    for (int i = 0; i < HASH_SIZE; i++) {
        PrecisionEntry* entry = hash_table[i];
        while (entry) {
            if (entry->birthdate_precision >= 0) {
                sqlite3_bind_int(stmt, 1, entry->birthdate_precision);
            } else {
                sqlite3_bind_null(stmt, 1);
            }

            if (entry->deathdate_precision >= 0) {
                sqlite3_bind_int(stmt, 2, entry->deathdate_precision);
            } else {
                sqlite3_bind_null(stmt, 2);
            }

            sqlite3_bind_text(stmt, 3, entry->wikidata_id, -1, SQLITE_STATIC);

            sqlite3_step(stmt);
            sqlite3_reset(stmt);

            updated++;
            batch_count++;

            if (updated % 100000 == 0) {
                printf("\r  %ld rows updated...", updated);
                fflush(stdout);
            }

            if (batch_count >= BATCH_SIZE) {
                sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
                sqlite3_exec(db, "BEGIN TRANSACTION", NULL, NULL, NULL);
                batch_count = 0;
            }

            entry = entry->next;
        }
    }

    sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);
    sqlite3_finalize(stmt);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("\r  Updated %ld rows in %.1fs\n", updated, elapsed);

    /* Create indexes on precision columns */
    printf("\n[5/5] Creating indexes...\n");
    fflush(stdout);
    start = clock();

    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_birthdate_precision ON individuals(birthdate_precision)", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_deathdate_precision ON individuals(deathdate_precision)", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  Indexes created in %.1fs\n", elapsed);

    /* Cleanup */
    hash_free();
    sqlite3_close(db);

    printf("\n============================================================\n");
    printf("DONE!\n");
    printf("============================================================\n");

    return 0;
}
