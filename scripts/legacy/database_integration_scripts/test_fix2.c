#include <stdio.h>
#include <string.h>
#include <stdint.h>

#define MAX_STR 65536

static int has_mojibake(const char* s) {
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        if (p[0] == 0xC3 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        if (p[0] == 0xC2 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        p++;
    }
    return 0;
}

static int is_valid_utf8(const unsigned char* s, size_t len) {
    for (size_t i = 0; i < len;) {
        if (s[i] < 0x80) i++;
        else if ((s[i] & 0xE0) == 0xC0 && i+1 < len && (s[i+1] & 0xC0) == 0x80) i += 2;
        else if ((s[i] & 0xF0) == 0xE0 && i+2 < len) i += 3;
        else if ((s[i] & 0xF8) == 0xF0 && i+3 < len) i += 4;
        else return 0;
    }
    return 1;
}

static int fix_utf8(const char* in, char* out, size_t max) {
    if (!in || !has_mojibake(in)) { strcpy(out, in ? in : ""); return 0; }

    unsigned char tmp[MAX_STR];
    size_t len = 0;
    const unsigned char* p = (const unsigned char*)in;

    while (*p && len < MAX_STR - 1) {
        uint32_t cp; int skip;
        if ((*p & 0x80) == 0) { cp = *p; skip = 1; }
        else if ((*p & 0xE0) == 0xC0) { cp = ((*p & 0x1F) << 6) | (p[1] & 0x3F); skip = 2; }
        else if ((*p & 0xF0) == 0xE0) { cp = ((*p & 0x0F) << 12) | ((p[1] & 0x3F) << 6) | (p[2] & 0x3F); skip = 3; }
        else if ((*p & 0xF8) == 0xF0) { cp = ((*p & 0x07) << 18) | ((p[1] & 0x3F) << 12) | ((p[2] & 0x3F) << 6) | (p[3] & 0x3F); skip = 4; }
        else { tmp[len++] = *p++; continue; }

        if (cp < 256) tmp[len++] = (unsigned char)cp;
        else { strcpy(out, in); return 0; }
        p += skip;
    }
    tmp[len] = '\0';

    if (is_valid_utf8(tmp, len)) { memcpy(out, tmp, len + 1); return 1; }
    strcpy(out, in);
    return 0;
}

int main() {
    char out[1024];
    const char* test = "WÃ¼rzburg";
    
    int fixed = fix_utf8(test, out, sizeof(out));
    printf("Input:  %s\n", test);
    printf("Output: %s\n", out);
    printf("Fixed: %d\n", fixed);
    
    // Hex output
    printf("Out hex: ");
    for (const unsigned char* p = (const unsigned char*)out; *p; p++) {
        printf("%02X ", *p);
    }
    printf("\n");
    return 0;
}
