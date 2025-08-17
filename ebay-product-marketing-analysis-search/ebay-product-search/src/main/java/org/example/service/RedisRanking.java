package org.example.service;

import org.example.message.Product;
import org.example.message.ProductRanking;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.*;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class RedisRanking {
    @Autowired
    private RedisTemplate<String, Object> redisTemplate;
    @Value("${review-rank-key}")
    private String reviewRankKey;

    @Value("${brand-rank-key}")
    private String brandRankKey;

    public void reviewsRanking(List<Product> products) {
        Set<ZSetOperations.TypedTuple<Object>> tuples = new HashSet<>();
        products.forEach(p ->
                tuples.add(new DefaultTypedTuple<>(p.getUniqId(),
                        p.getSellerNumOfReviews().doubleValue())));
        redisTemplate.opsForZSet().add(reviewRankKey, tuples);
    }

    public void brandRanking(List<Product> products) {
        redisTemplate.executePipelined(new SessionCallback<>() {
            @Override
            public Object execute(RedisOperations operations) throws DataAccessException {
                for (Product product : products) {
                    operations.opsForZSet().incrementScore(brandRankKey, product.getManufacturer(), 1.0);
                }
                return null;
            }
        });
    }

    public List<ProductRanking> getReviewRankings(int s, int e) {
        return getProductRankings(reviewRankKey, s, e);
    }

    public List<ProductRanking> getBrandRankings(int s, int e) {
        return getProductRankings(brandRankKey, s, e);
    }

    private List<ProductRanking> getProductRankings(String rankKey, int s, int e) {
        Set<ZSetOperations.TypedTuple<Object>> topRanks = redisTemplate.opsForZSet()
                .reverseRangeWithScores(rankKey, s, e);
        List<ProductRanking> productRankings = new ArrayList<>();
        for(ZSetOperations.TypedTuple<Object> entry : topRanks) {
            productRankings.add(new ProductRanking((String) entry.getValue(), entry.getScore().longValue()));
        }
        return productRankings;
    }
}
