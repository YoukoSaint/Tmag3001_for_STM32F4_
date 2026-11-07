#ifndef TEST_HARNESS_H
#define TEST_HARNESS_H

#include <stdio.h>

static unsigned long g_checks = 0;
static unsigned long g_failures = 0;

#define CHECK(condition, ...)                                                 \
    do {                                                                      \
        ++g_checks;                                                           \
        if (!(condition)) {                                                   \
            ++g_failures;                                                     \
            printf("%s:%d: FAILED: ", __FILE__, __LINE__);                    \
            printf(__VA_ARGS__);                                              \
            printf("\n");                                                   \
        }                                                                     \
    } while (0)

#define CHECK_EQ_U8(actual, expected)                                          \
    do {                                                                      \
        const unsigned long long ht_actual_u8 =                               \
            (unsigned long long)(actual);                                     \
        const unsigned long long ht_expected_u8 =                             \
            (unsigned long long)(expected);                                   \
        CHECK(ht_actual_u8 == ht_expected_u8,                                  \
              "expected %llu, actual %llu",                                  \
              ht_expected_u8, ht_actual_u8);                                  \
    } while (0)

#define CHECK_EQ_U16(actual, expected)                                         \
    do {                                                                      \
        const unsigned long long ht_actual_u16 =                              \
            (unsigned long long)(actual);                                     \
        const unsigned long long ht_expected_u16 =                            \
            (unsigned long long)(expected);                                   \
        CHECK(ht_actual_u16 == ht_expected_u16,                                \
              "expected %llu, actual %llu",                                  \
              ht_expected_u16, ht_actual_u16);                                \
    } while (0)

static int test_report(void)
{
    if (g_failures == 0) {
        printf("OK: %lu/%lu checks passed\n", g_checks, g_checks);
        return 0;
    }

    printf("FAILED: %lu/%lu checks passed (%lu failed)\n",
           g_checks - g_failures, g_checks, g_failures);
    return 1;
}

#define TEST_REPORT()                                                         \
    do {                                                                      \
        return test_report();                                                 \
    } while (0)

#endif
