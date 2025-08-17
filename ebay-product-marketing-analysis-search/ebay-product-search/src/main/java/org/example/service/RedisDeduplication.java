package org.example.service;

import org.example.message.Product;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class RedisDeduplication {
    @Autowired
    private RedisTemplate<String, Object> redisTemplate;
    private final String keyPrefix = "product-deduplication:";
    @Value("${redis-expire-seconds}")
    private long expireSeconds;

    public List<Product> filterAndMarkNewProducts(List<Product> products) {
        List<String> uniqIds = products.stream()
                .map(Product::getUniqId)
                .collect(Collectors.toList());

        // 使用 Lua 脚本批量检查并设置
        List<String> existsList = checkAndMarkBatch(uniqIds);

        // 筛选出未存在的数据
        List<Product> filtered = new ArrayList<>();
        for (int i = 0; i < products.size(); i++) {
            if (existsList.get(i).equals("0")) {
                filtered.add(products.get(i));
            }
        }
        return filtered;
    }

    private List<String> checkAndMarkBatch(List<String> uniqIds) {
        // Lua 脚本：检查键是否存在，若不存在则设置并返回 false
        String script = "local exists = {} " +
                "for i, key in ipairs(KEYS) do " +
                "   if redis.call('EXISTS', key) == 1 then " +
                "       exists[i] = '1' " +
                "   else " +
                "       redis.call('SET', key, '1', 'EX', ARGV[1]) " +
                "       exists[i] = '0' " +
                "   end " +
                "end " +
                "return exists";

        // 执行 Lua 脚本
        RedisScript<List> redisScript = new DefaultRedisScript<>(script, List.class);
        
        return (List<String>) redisTemplate.execute(
                redisScript,
                uniqIds.stream().map(k -> keyPrefix + k).collect(Collectors.toList()),
                String.valueOf(expireSeconds)
        );
    }
}
