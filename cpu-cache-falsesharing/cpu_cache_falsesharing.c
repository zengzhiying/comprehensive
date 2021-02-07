#include <stdio.h>
#include <time.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/time.h>
#include <pthread.h>

struct LongValue {
    // volatile关键字 避免寄存器读取
    volatile long long value;
    // 跳过高速缓存行 目前64位cpu大小一般为64Byte
    // long long p1, p2, p3, p4, p5, p6, p7;
};

int main(int argc, char const *argv[])
{
    // printf("size: %d\n", sizeof(long long));
    // printf("size: %d\n", sizeof(struct LongValue));

    struct LongValue values[4];
    pthread_t threads[4];

    void *test_thread(void *vargp);

    struct timeval time1, time2;
    double time_cost;

    gettimeofday(&time1, NULL);

    for(int i = 0; i < 4; i++) {
        pthread_create(&threads[i], NULL, test_thread, (void *)&values[i]);
    }

    for(int i = 0; i < 4; i++) {
        pthread_join(threads[i], NULL);
    }

    gettimeofday(&time2, NULL);
    time_cost = (time2.tv_sec - time1.tv_sec) + (time2.tv_usec - time1.tv_usec) / 1e6;
    printf("time: %lfs\n", time_cost);
    // 伪共享大约: 1.3s
    // 跳过缓存行: 0.37s左右

    return 0;
}


void *test_thread(void *vargp) {
    struct LongValue *v = (struct LongValue *) vargp;
    for(int i = 0; i < 100000000; i++) {
        v->value = i;
    }
}
