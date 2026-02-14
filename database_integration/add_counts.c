/*
 * Add count columns - FAST: pre-aggregate then join
 * gcc -O3 -o add_counts add_counts.c -lsqlite3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>

#define BATCH 50000

static void insert_values(sqlite3_stmt* stmt, const char* str) {
    if (!str || !*str) return;
    char* copy = strdup(str);
    char* token = strtok(copy, ";");
    while (token) {
        while (*token == ' ') token++;
        char* end = token + strlen(token) - 1;
        while (end > token && *end == ' ') *end-- = '\0';
        if (*token) {
            sqlite3_bind_text(stmt, 1, token, -1, SQLITE_TRANSIENT);
            sqlite3_step(stmt);
            sqlite3_reset(stmt);
        }
        token = strtok(NULL, ";");
    }
    free(copy);
}

int main(int argc, char* argv[]) {
    if (argc != 2) { fprintf(stderr, "Usage: %s <database.sqlite3>\n", argv[0]); return 1; }

    sqlite3 *db;
    sqlite3_stmt *stmt, *ins;
    char* err = NULL;

    if (sqlite3_open(argv[1], &db) != SQLITE_OK) {
        fprintf(stderr, "Cannot open DB\n"); return 1;
    }

    sqlite3_exec(db, "PRAGMA synchronous=OFF;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA journal_mode=MEMORY;", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA cache_size=200000;", NULL, NULL, NULL);

    /* ========== OCCUPATIONS ========== */
    printf("[1/3] Counting occupations...\n"); fflush(stdout);

    sqlite3_exec(db, "DROP TABLE IF EXISTS _tmp;", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE TEMP TABLE _tmp (name TEXT);", NULL, NULL, NULL);
    sqlite3_prepare_v2(db, "INSERT INTO _tmp VALUES (?)", -1, &ins, NULL);
    sqlite3_prepare_v2(db, "SELECT occupations_en FROM individuals WHERE occupations_en IS NOT NULL", -1, &stmt, NULL);

    sqlite3_exec(db, "BEGIN;", NULL, NULL, NULL);
    long rows = 0, batch = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        insert_values(ins, (const char*)sqlite3_column_text(stmt, 0));
        rows++; batch++;
        if (batch >= BATCH) { sqlite3_exec(db, "COMMIT;BEGIN;", NULL, NULL, NULL); batch = 0; }
        if (rows % 500000 == 0) { printf("\r  Scanned %ld rows...", rows); fflush(stdout); }
    }
    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    sqlite3_finalize(ins);
    printf("\r  Scanned %ld rows        \n", rows); fflush(stdout);

    /* Pre-aggregate into indexed table */
    printf("  Aggregating..."); fflush(stdout);
    sqlite3_exec(db, "CREATE TEMP TABLE _counts AS SELECT name, COUNT(*) as cnt FROM _tmp GROUP BY name;", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX _counts_idx ON _counts(name);", NULL, NULL, NULL);
    sqlite3_exec(db, "DROP TABLE _tmp;", NULL, NULL, NULL);
    printf(" ✓\n");

    /* Update with join */
    printf("  Updating..."); fflush(stdout);
    sqlite3_exec(db, "UPDATE occupations SET count = 0;", NULL, NULL, NULL);
    sqlite3_exec(db,
        "UPDATE occupations SET count = (SELECT cnt FROM _counts WHERE _counts.name = occupations.name_en) "
        "WHERE EXISTS (SELECT 1 FROM _counts WHERE _counts.name = occupations.name_en);",
        NULL, NULL, NULL);
    sqlite3_exec(db, "DROP TABLE _counts;", NULL, NULL, NULL);
    printf(" ✓\n");

    /* ========== CITIES ========== */
    printf("[2/3] Counting cities...\n"); fflush(stdout);

    sqlite3_exec(db, "CREATE TEMP TABLE _tmp (name TEXT);", NULL, NULL, NULL);
    sqlite3_prepare_v2(db, "INSERT INTO _tmp VALUES (?)", -1, &ins, NULL);

    sqlite3_prepare_v2(db, "SELECT birthcity_en FROM individuals WHERE birthcity_en IS NOT NULL", -1, &stmt, NULL);
    sqlite3_exec(db, "BEGIN;", NULL, NULL, NULL);
    rows = 0; batch = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        sqlite3_bind_text(ins, 1, (const char*)sqlite3_column_text(stmt, 0), -1, SQLITE_STATIC);
        sqlite3_step(ins); sqlite3_reset(ins);
        rows++; batch++;
        if (batch >= BATCH) { sqlite3_exec(db, "COMMIT;BEGIN;", NULL, NULL, NULL); batch = 0; }
        if (rows % 500000 == 0) { printf("\r  Scanned %ld birthcities...", rows); fflush(stdout); }
    }
    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    printf("\r  Scanned %ld birthcities    \n", rows); fflush(stdout);

    int rc2 = sqlite3_prepare_v2(db, "SELECT deathcity_en FROM individuals WHERE deathcity_en IS NOT NULL", -1, &stmt, NULL);
    if (rc2 != SQLITE_OK) { fprintf(stderr, "Error preparing deathcity: %s\n", sqlite3_errmsg(db)); }
    sqlite3_exec(db, "BEGIN;", NULL, NULL, NULL);
    rows = 0; batch = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        sqlite3_bind_text(ins, 1, (const char*)sqlite3_column_text(stmt, 0), -1, SQLITE_STATIC);
        sqlite3_step(ins); sqlite3_reset(ins);
        rows++; batch++;
        if (batch >= BATCH) { sqlite3_exec(db, "COMMIT;BEGIN;", NULL, NULL, NULL); batch = 0; }
        if (rows % 500000 == 0) { printf("\r  Scanned %ld deathcities...", rows); fflush(stdout); }
    }
    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    sqlite3_finalize(ins);
    printf("\r  Scanned %ld deathcities    \n", rows); fflush(stdout);

    printf("  Aggregating..."); fflush(stdout);
    sqlite3_exec(db, "CREATE TEMP TABLE _counts AS SELECT name, COUNT(*) as cnt FROM _tmp GROUP BY name;", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX _counts_idx ON _counts(name);", NULL, NULL, NULL);
    sqlite3_exec(db, "DROP TABLE _tmp;", NULL, NULL, NULL);
    printf(" ✓\n");

    printf("  Updating..."); fflush(stdout);
    sqlite3_exec(db, "UPDATE cities SET count = 0;", NULL, NULL, NULL);
    sqlite3_exec(db,
        "UPDATE cities SET count = (SELECT cnt FROM _counts WHERE _counts.name = cities.name_en) "
        "WHERE EXISTS (SELECT 1 FROM _counts WHERE _counts.name = cities.name_en);",
        NULL, NULL, NULL);
    sqlite3_exec(db, "DROP TABLE _counts;", NULL, NULL, NULL);
    printf(" ✓\n");

    /* ========== NATIONALITIES ========== */
    printf("[3/3] Building nationalities...\n"); fflush(stdout);

    sqlite3_exec(db, "CREATE TEMP TABLE _tmp (name TEXT);", NULL, NULL, NULL);
    sqlite3_prepare_v2(db, "INSERT INTO _tmp VALUES (?)", -1, &ins, NULL);
    sqlite3_prepare_v2(db, "SELECT nationalities_en FROM individuals WHERE nationalities_en IS NOT NULL", -1, &stmt, NULL);

    sqlite3_exec(db, "BEGIN;", NULL, NULL, NULL);
    rows = 0; batch = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        insert_values(ins, (const char*)sqlite3_column_text(stmt, 0));
        rows++; batch++;
        if (batch >= BATCH) { sqlite3_exec(db, "COMMIT;BEGIN;", NULL, NULL, NULL); batch = 0; }
        if (rows % 500000 == 0) { printf("\r  Scanned %ld rows...", rows); fflush(stdout); }
    }
    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    sqlite3_finalize(stmt);
    sqlite3_finalize(ins);
    printf("\r  Scanned %ld rows          \n", rows); fflush(stdout);

    printf("  Creating table..."); fflush(stdout);
    sqlite3_exec(db, "DROP TABLE IF EXISTS nationalities;", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE TABLE nationalities AS SELECT name AS name_en, COUNT(*) AS count FROM _tmp WHERE name != '' GROUP BY name;", NULL, NULL, &err);
    if (err) { fprintf(stderr, " Error: %s\n", err); sqlite3_free(err); }
    else printf(" ✓\n");
    sqlite3_exec(db, "DROP TABLE _tmp;", NULL, NULL, NULL);

    sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM nationalities", -1, &stmt, NULL);
    sqlite3_step(stmt);
    printf("  %lld nationalities\n", sqlite3_column_int64(stmt, 0));
    sqlite3_finalize(stmt);

    printf("Creating indexes..."); fflush(stdout);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_occ_count ON occupations(count DESC);", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_city_count ON cities(count DESC);", NULL, NULL, NULL);
    sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_nat_count ON nationalities(count DESC);", NULL, NULL, NULL);
    printf(" ✓\nDone!\n");

    sqlite3_close(db);
    return 0;
}
