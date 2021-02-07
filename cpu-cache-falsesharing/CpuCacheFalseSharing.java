

public class CpuCacheFalseSharing implements Runnable {
    public static int NUM_THREADS = 4;
    public final static long ITERATIONS = 5000L * 1000L ;
    private final int arrayIndex;
    private static VolatileLong[] longs;
    public static long SUM_TIME = 01;
    public CpuCacheFalseSharing(final int arrayIndex) {
        this.arrayIndex = arrayIndex;
    }


    public static void main(final String[] args) throws Exception {
        for(int j = 0; j < 10; j ++ ) {
            if (args.length == 1) {
                NUM_THREADS = Integer.parseInt(args[0]);
            }

            longs = new VolatileLong[NUM_THREADS];
            // 和下面a1,a2,a3,a4作用相同 开32个字节 保证longs对象缓存不失效
            Long[] longs1 = new Long[]{10L, 11L, 12L};
            for(int i = 0; i < longs.length; i++) {
                longs[i] = new VolatileLong();
            }

            final long start = System.nanoTime();
            runTest();
            final long end = System.nanoTime();
            SUM_TIME += end-start;
        }

        System.out.println("平均耗时: "+ SUM_TIME/10000000L + "ms");
    }


    private static void runTest() throws InterruptedException {
        Thread[] threads = new Thread[NUM_THREADS];
        for (int i = 0; i < threads.length; i++) {
            threads[i] = new Thread(new CpuCacheFalseSharing(i));
        }

        for (Thread t : threads) {
            t.start();
        }

        for (Thread t : threads) {
            t.join();
        }
    }

    @Override
    public void run() {
        long i = ITERATIONS + 1;
        while (0 != --i) {
            longs[arrayIndex].value = i;
        }
    }

    public final static class VolatileLong {
        // 保护前面数组不受修改速度会更快
        // public long a1, a2, a3, a4;
        public volatile long value = 0L;
        // 取消注释后 运行速度加快
        public long p1, p2, p3, p4, p5, p6;
    }
}
