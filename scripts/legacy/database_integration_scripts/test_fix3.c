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
    // Build string from hex: 456C69C385C2A16B6120486C6164696C6F76C383C2A1
    unsigned char test[] = {0x45, 0x6C, 0x69, 0xC3, 0x85, 0xC2, 0xA1, 0x6B, 0x61, 0x20, 
                            0x48, 0x6C, 0x61, 0x64, 0x69, 0x6C, 0x6F, 0x76, 0xC3, 0x83, 0xC2, 0xA1, 0x00};
    char out[1024];
    
    printf("Input:  %s\n", test);
    printf("Has mojibake: %d\n", has_mojibake((char*)test));
    
    int fixed = fix_utf8((char*)test, out, sizeof(out));
    printf("Output: %s\n", out);
    printf("Fixed: %d\n", fixed);
    return 0;
}
