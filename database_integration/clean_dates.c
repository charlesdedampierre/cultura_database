/*
 * Clean dates: remove T00:00:00Z suffix
 * gcc -O3 -o clean_dates clean_dates.c -lsqlite3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>

int main(int argc, char* argv[]) {
    if (argc != 2) { fprintf(stderr, "Usage: %s <database.sqlite3>\n", argv[0]); return 1; }

    sqlite3 *db;
    if (sqlite3_open(argv[1], &db) != SQLITE_OK) {
        fprintf(stderr, "Cannot open DB\n"); return 1;
    }

    printf("Cleaning dates...\n"); fflush(stdout);

    /* Remove T00:00:00Z from birthdate and deathdate */
    int rc = sqlite3_exec(db,
        "UPDATE individuals SET birthdate = REPLACE(birthdate, 'T00:00:00Z', '') "
        "WHERE birthdate LIKE '%T00:00:00Z';",
        NULL, NULL, NULL);

    if (rc != SQLITE_OK) {
        fprintf(stderr, "Error updating birthdate: %s\n", sqlite3_errmsg(db));
    } else {
        printf("  ✓ birthdate cleaned (%d rows)\n", sqlite3_changes(db));
    }
    fflush(stdout);

    rc = sqlite3_exec(db,
        "UPDATE individuals SET deathdate = REPLACE(deathdate, 'T00:00:00Z', '') "
        "WHERE deathdate LIKE '%T00:00:00Z';",
        NULL, NULL, NULL);

    if (rc != SQLITE_OK) {
        fprintf(stderr, "Error updating deathdate: %s\n", sqlite3_errmsg(db));
    } else {
        printf("  ✓ deathdate cleaned (%d rows)\n", sqlite3_changes(db));
    }

    sqlite3_close(db);
    printf("Done!\n");
    return 0;
}
