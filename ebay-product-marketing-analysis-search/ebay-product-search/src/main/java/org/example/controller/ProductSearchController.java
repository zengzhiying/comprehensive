package org.example.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import org.example.message.Product;
import org.example.service.ElasticsearchService;
import org.example.service.MySqlService;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.yaml.snakeyaml.util.Tuple;

import java.io.IOException;
import java.util.*;

@RestController
@RequestMapping("/api/product")
public class ProductSearchController {
    private final ElasticsearchService elasticsearchService;
    private final MySqlService mySqlService;

    public ProductSearchController(ElasticsearchService elasticsearchService, MySqlService mySqlService) {
        this.elasticsearchService = elasticsearchService;
        this.mySqlService = mySqlService;
    }

    @GetMapping("/search")
    public List<Product> search(
            @RequestParam(required = false) String manufacturer,
            @RequestParam(required = false) String content) throws IOException {
        if(manufacturer == null && content == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "manufacturer and content is null");
        }
        Pageable pageable = PageRequest.of(0, 50);
        if(manufacturer != null) {
            if(manufacturer.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "manufacturer is empty");
            }
            return mySqlService.getProductsByManufacturer(manufacturer, pageable);
        } else {
            if(content.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "content is empty");
            }
            List<Tuple<String, Double>> idAndScores = elasticsearchService.searchByContent(content, pageable);
            if(idAndScores.isEmpty()) {
                return List.of();
            }
            List<String> ids = idAndScores.stream().map(t -> t._1()).toList();
            List<Product> queryProducts = mySqlService.getProductsByIds(ids);

            Map<String, Double> orderMap = new HashMap<>();
            for(int i = 0; i < idAndScores.size(); i++) {
                orderMap.put(idAndScores.get(i)._1(), idAndScores.get(i)._2());
            }

            List<Product> products = new ArrayList<>(queryProducts);
            Collections.sort(products, Comparator.comparingDouble(p -> -orderMap.get(p.getUniqId())));

            return products;
        }
    }

    @GetMapping("/{id}")
    public Product getProduct(@PathVariable String id) throws JsonProcessingException {
        return mySqlService.getProductById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Product not found"));
    }
}
