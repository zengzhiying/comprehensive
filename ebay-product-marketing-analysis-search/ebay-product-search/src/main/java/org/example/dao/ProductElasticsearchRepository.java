package org.example.dao;

import org.example.message.ProductIndex;
import org.springframework.data.elasticsearch.repository.ElasticsearchRepository;

public interface ProductElasticsearchRepository extends ElasticsearchRepository<ProductIndex, String> {
}

