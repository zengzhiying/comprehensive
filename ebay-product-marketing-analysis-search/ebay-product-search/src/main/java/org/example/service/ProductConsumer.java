package org.example.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.example.message.Product;
import org.example.dao.ProductMySqlRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

@Component
public class ProductConsumer {
    private final ProductMySqlRepository productRepository;
    private final ElasticsearchService elasticsearchService;
    private final RedisDeduplication redisDeduplication;
    private final RedisRanking redisRanking;
    @Value("${batch-size}")
    private int batchSize;  // 批量处理阈值

    private List<Product> batch = new ArrayList<>();
    private final Object lock = new Object();
    private AtomicInteger batchCount = new AtomicInteger(0);
    private int prevBatchCount = 0;

    public ProductConsumer(ProductMySqlRepository productRepository,
                           ElasticsearchService elasticsearchService,
                           RedisDeduplication redisDeduplication,
                           RedisRanking redisRanking) {
        this.productRepository = productRepository;
        this.elasticsearchService = elasticsearchService;
        this.redisDeduplication = redisDeduplication;
        this.redisRanking = redisRanking;
    }

    @KafkaListener(topics = "${spring.kafka.product-topic}")
    public void listen(String message, Acknowledgment ack) {
        try {
            Product product = new ObjectMapper().readValue(message, Product.class);
            if(product.getModelNum().length() > 100) {
                System.out.println("uniq id: " + product.getUniqId() + " data too long " +
                        product.getModelNum().length() + " skip.");
                ack.acknowledge();
                return;
            }
            synchronized (lock) {
                batch.add(product);
                if(batch.size() >= batchSize) {
                    flushBatch();
                    batchCount.incrementAndGet();
                }
            }
            ack.acknowledge();
        } catch (Exception e) {
            e.printStackTrace();
            ack.acknowledge();
        }
    }

    private void flushBatch() {
        if(!batch.isEmpty()) {
            try {
                List<Product> filterBatch = redisDeduplication.filterAndMarkNewProducts(batch);
                if(!filterBatch.isEmpty()) {
                    System.out.println("过滤后批量条数: " + filterBatch.size());
                    productRepository.saveAll(filterBatch);
                    elasticsearchService.bulkIndexProducts(filterBatch);
                    redisRanking.reviewsRanking(filterBatch);
                    redisRanking.brandRanking(filterBatch);
                }
            } catch (Exception e) {
                e.printStackTrace();
            }
            batch.clear();
        }
    }

    @Scheduled(fixedDelay = 30000)
    private void backgroundFlush() {
        if(batchCount.get() > prevBatchCount) {
            prevBatchCount = batchCount.get();
            return;
        }
        synchronized (lock) {
            flushBatch();
        }
    }

}
