package org.example.configuration;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.StringRedisSerializer;

@Configuration
public class RedisConfig {
    @Bean
    public RedisTemplate redisTemplate(RedisConnectionFactory connectionFactory) {
        RedisTemplate template = new RedisTemplate<>();
        template.setConnectionFactory(connectionFactory);

        // 设置键（Key）的序列化方式为 String
        template.setKeySerializer(new StringRedisSerializer());
        // 设置值（Value）的序列化方式为 String
        template.setValueSerializer(new StringRedisSerializer());
//
//        // 哈希键（Hash Key）的序列化
//        template.setHashKeySerializer(new StringRedisSerializer());
//        // 哈希值（Hash Value）的序列化
//        template.setHashValueSerializer(new GenericJackson2JsonRedisSerializer());

        return template;
    }
}
