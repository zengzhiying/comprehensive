package org.example.controller;

import org.example.message.Product;
import org.example.message.ProductRanking;
import org.example.service.MySqlService;
import org.example.service.RedisRanking;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;


@RestController
@RequestMapping("/api/product")
public class ProductRankingController {
    private final RedisRanking redisRanking;
    private final MySqlService mySqlService;
    private final int limit = 10;

    public ProductRankingController(RedisRanking redisRanking, MySqlService mySqlService) {
        this.redisRanking = redisRanking;
        this.mySqlService = mySqlService;
    }

    @GetMapping("/review-ranking")
    public List<Product> reviewRanking() {
        List<ProductRanking> reviewRankings = redisRanking.getReviewRankings(0, limit - 1);
        List<String> productIds = reviewRankings.stream().map(ProductRanking::getKey).toList();
        return mySqlService.getProductsByIdsWithOrder(productIds);
    }

    @GetMapping("/brand-ranking")
    public List<ProductRanking> brandRanking() {
        return redisRanking.getBrandRankings(0, limit - 1);
    }
}
