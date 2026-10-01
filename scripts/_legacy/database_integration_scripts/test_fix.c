#include <stdio.h>
#include <string.h>
#include <stdint.h>

static int has_mojibake(const char* s) {
    const unsigned char* p = (const unsigned char*)s;
    while (*p) {
        if (p[0] == 0xC3 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        if (p[0] == 0xC2 && p[1] >= 0x80 && p[1] <= 0xBF) return 1;
        p++;
    }
    return 0;
}

int main() {
    const char* test = "WÃ¼rzburg";
    printf("Input: %s\n", test);
    printf("Has mojibake: %d\n", has_mojibake(test));
    
    // Print hex bytes
    printf("Hex: ");
    for (const unsigned char* p = (const unsigned char*)test; *p; p++) {
        printf("%02X ", *p);
    }
    printf("\n");
    return 0;
}
