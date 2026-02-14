/*
 * Clean SQLite database: remove quotes and @en tags, rename columns with _en suffix.
 *
 * Compile: gcc -O3 -o clean_sqlite clean_sqlite.c -lsqlite3
 * Run: ./clean_sqlite ../data/all_humans/humans.sqlite3 ../data/all_humans/humans_clean.sqlite3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <time.h>

#define BATCH_SIZE 50000

/* Clean a string: remove " and @en */
char* clean_string(const char* input, char* output, size_t max_len) {
    if (input == NULL) {
        output[0] = '\0';
        return output;
    }

    size_t j = 0;
    size_t len = strlen(input);

    for (size_t i = 0; i < len && j < max_len - 1; i++) {
        /* Skip double quotes */
        if (input[i] == '"') {
            continue;
        }
        /* Skip @en at end */
        if (i + 3 <= len && input[i] == '@' && input[i+1] == 'e' && input[i+2] == 'n') {
            /* Check if it's at end or followed by ; */
            if (i + 3 == len || input[i+3] == ';' || input[i+3] == ' ') {
                i += 2; /* Skip @en (loop will increment once more) */
                continue;
            }
        }
        output[j++] = input[i];
    }
    output[j] = '\0';

    /* Trim trailing/leading spaces */
    while (j > 0 && (output[j-1] == ' ' || output[j-1] == ';')) {
        output[--j] = '\0';
    }
    char* start = output;
    while (*start == ' ') start++;
    if (start != output) {
        memmove(output, start, strlen(start) + 1);
    }

    return output;
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
    printf("CLEAN SQLITE DATABASE (C)\n");
    printf("============================================================\n\n");

    /* Open input database */
    printf("[1/5] Opening input database...\n");
    rc = sqlite3_open_v2(input_path, &db_in, SQLITE_OPEN_READONLY, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot open input database: %s\n", sqlite3_errmsg(db_in));
        return 1;
    }
    printf("  ✓ Opened %s\n", input_path);

    /* Remove output if exists and create new */
    remove(output_path);

    printf("\n[2/5] Creating output database...\n");
    rc = sqlite3_open(output_path, &db_out);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot create output database: %s\n", sqlite3_errmsg(db_out));
        return 1;
    }

    /* Optimize for speed */
    sqlite3_exec(db_out, "PRAGMA synchronous = OFF", NULL, NULL, NULL);
    sqlite3_exec(db_out, "PRAGMA journal_mode = MEMORY", NULL, NULL, NULL);
    sqlite3_exec(db_out, "PRAGMA cache_size = 1000000", NULL, NULL, NULL);

    /* Create schema with _en columns */
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
        "  name_en TEXT"
        ");"
        "CREATE TABLE cities ("
        "  id TEXT PRIMARY KEY,"
        "  name_en TEXT"
        ");";

    rc = sqlite3_exec(db_out, create_sql, NULL, NULL, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot create schema: %s\n", sqlite3_errmsg(db_out));
        return 1;
    }
    printf("  ✓ Schema created with _en columns\n");

    /* Process individuals */
    printf("\n[3/5] Processing individuals...\n");
    clock_t start = clock();

    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    const char* select_sql = "SELECT wikidata_id, name, description, birthdate, deathdate, "
                             "nationalities, birthcity, deathcity, occupations FROM individuals";
    rc = sqlite3_prepare_v2(db_in, select_sql, -1, &stmt_read, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot prepare select: %s\n", sqlite3_errmsg(db_in));
        return 1;
    }

    const char* insert_sql = "INSERT INTO individuals VALUES (?,?,?,?,?,?,?,?,?)";
    rc = sqlite3_prepare_v2(db_out, insert_sql, -1, &stmt_write, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "Cannot prepare insert: %s\n", sqlite3_errmsg(db_out));
        return 1;
    }

    char buffer[65536];
    long count = 0;

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        /* wikidata_id (no cleaning needed) */
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);

        /* Clean text columns */
        for (int i = 1; i <= 8; i++) {
            const char* val = (const char*)sqlite3_column_text(stmt_read, i);
            if (val) {
                clean_string(val, buffer, sizeof(buffer));
                if (buffer[0]) {
                    sqlite3_bind_text(stmt_write, i + 1, buffer, -1, SQLITE_TRANSIENT);
                } else {
                    sqlite3_bind_null(stmt_write, i + 1);
                }
            } else {
                sqlite3_bind_null(stmt_write, i + 1);
            }
        }

        sqlite3_step(stmt_write);
        sqlite3_reset(stmt_write);

        count++;
        if (count % 500000 == 0) {
            printf("  %ld rows processed...\n", count);
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
    printf("  ✓ %ld individuals in %.1fs\n", count, elapsed);

    /* Process occupations */
    printf("\n[4/5] Processing lookup tables...\n");
    start = clock();

    sqlite3_exec(db_out, "BEGIN TRANSACTION", NULL, NULL, NULL);

    rc = sqlite3_prepare_v2(db_in, "SELECT id, name FROM occupations", -1, &stmt_read, NULL);
    rc = sqlite3_prepare_v2(db_out, "INSERT INTO occupations VALUES (?,?)", -1, &stmt_write, NULL);

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);
        const char* name = (const char*)sqlite3_column_text(stmt_read, 1);
        if (name) {
            clean_string(name, buffer, sizeof(buffer));
            sqlite3_bind_text(stmt_write, 2, buffer, -1, SQLITE_TRANSIENT);
        } else {
            sqlite3_bind_null(stmt_write, 2);
        }
        sqlite3_step(stmt_write);
        sqlite3_reset(stmt_write);
    }
    sqlite3_finalize(stmt_read);
    sqlite3_finalize(stmt_write);

    /* Process cities */
    rc = sqlite3_prepare_v2(db_in, "SELECT id, name FROM cities", -1, &stmt_read, NULL);
    rc = sqlite3_prepare_v2(db_out, "INSERT INTO cities VALUES (?,?)", -1, &stmt_write, NULL);

    while (sqlite3_step(stmt_read) == SQLITE_ROW) {
        sqlite3_bind_text(stmt_write, 1, (const char*)sqlite3_column_text(stmt_read, 0), -1, SQLITE_TRANSIENT);
        const char* name = (const char*)sqlite3_column_text(stmt_read, 1);
        if (name) {
            clean_string(name, buffer, sizeof(buffer));
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
    printf("  ✓ Lookup tables in %.1fs\n", elapsed);

    /* Create indexes */
    printf("\n[5/5] Creating indexes...\n");
    start = clock();

    sqlite3_exec(db_out, "CREATE INDEX idx_name ON individuals(name_en)", NULL, NULL, NULL);
    sqlite3_exec(db_out, "CREATE INDEX idx_birthcity ON individuals(birthcity_en)", NULL, NULL, NULL);

    elapsed = (double)(clock() - start) / CLOCKS_PER_SEC;
    printf("  ✓ Indexes in %.1fs\n", elapsed);

    /* Close databases */
    sqlite3_close(db_in);
    sqlite3_close(db_out);

    printf("\n============================================================\n");
    printf("DONE!\n");
    printf("Output: %s\n", output_path);
    printf("============================================================\n");

    return 0;
}
