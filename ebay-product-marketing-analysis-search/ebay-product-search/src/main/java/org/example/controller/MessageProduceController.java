package org.example.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import org.example.message.Product;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public class MessageProduceController {
    private final KafkaTemplate<String, String> kafkaTemplate;
    @Value("${spring.kafka.product-topic}")
    private String produceTopic;

    @Autowired
    public MessageProduceController(KafkaTemplate<String, String> template) {
        this.kafkaTemplate = template;
    }

    @PostMapping("/product")
    public String postProduct(@Valid @RequestBody Product product, BindingResult bindingResult) throws JsonProcessingException {
        if(bindingResult.hasErrors()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, bindingResult.getAllErrors().toString());
        }

        String productMessage = new ObjectMapper().writeValueAsString(product);
        kafkaTemplate.send(produceTopic, productMessage);
        return "{\"message\": \"Data sent to Kafka successfully\"}";
    }
}
