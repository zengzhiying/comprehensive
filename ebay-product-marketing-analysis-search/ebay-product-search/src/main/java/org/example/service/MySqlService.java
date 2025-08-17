package org.example.service;

import org.example.dao.ProductMySqlRepository;
import org.example.message.Product;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class MySqlService {
    @Autowired
    private ProductMySqlRepository productMySqlRepository;

    public List<Product> getProductsByIds(List<String> ids) {
        return productMySqlRepository.findAvailableProductsByIds(ids, Pageable.ofSize(ids.size())).getContent();
    }

    public List<Product> getProductsByIdsWithOrder(List<String> ids) {
        Page<Product> productPage = productMySqlRepository.findAvailableProductsByIds(ids, Pageable.ofSize(ids.size()));
        List<Product> products = new ArrayList<>(productPage.getContent());

        Map<String, Integer> orderMap = new HashMap<>();
        for(int i = 0; i < ids.size(); i++) {
            orderMap.put(ids.get(i), i);
        }

        products.sort(Comparator.comparingInt(p -> orderMap.get(p.getUniqId())));
        return products;
    }

    public List<Product> getProductsByManufacturer(String manufacturer, Pageable pageable) {
        return productMySqlRepository.findAvailableProductsByManufacturer(manufacturer, pageable).getContent();
    }

    public Optional<Product> getProductById(String id) {
        return productMySqlRepository.findById(id);
    }
}
