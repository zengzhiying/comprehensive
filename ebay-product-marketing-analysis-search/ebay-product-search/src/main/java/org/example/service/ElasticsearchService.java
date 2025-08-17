package org.example.service;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.elasticsearch._types.query_dsl.BoolQuery;
import co.elastic.clients.elasticsearch._types.query_dsl.QueryBuilders;
import co.elastic.clients.elasticsearch.core.BulkRequest;
import co.elastic.clients.elasticsearch.core.BulkResponse;
import co.elastic.clients.elasticsearch.core.SearchResponse;
import co.elastic.clients.elasticsearch.core.bulk.BulkOperation;
import co.elastic.clients.elasticsearch.core.bulk.IndexOperation;
import co.elastic.clients.elasticsearch.core.search.HitsMetadata;
import org.example.message.Product;
import org.example.message.ProductIndex;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.util.Tuple;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class ElasticsearchService {
    @Autowired
    private ElasticsearchClient elasticsearchClient;

    @Value("${spring.elasticsearch.product-index}")
    private String productIndexName;

    public void bulkIndexProducts(List<Product> products) {
        List<BulkOperation> bulkOperations = products.stream()
                .filter(p -> p.getStock() == 1 && p.getDiscontinued() == 0 && p.getBrokenLink() == 0)
                .map(p -> new BulkOperation.Builder().index(new IndexOperation.Builder<Map<String, String>>()
                        .index(productIndexName)
                        .id(p.getUniqId())
                        .document(Map.of("title", p.getTitle(), "model_name", p.getModelName()))
                        .build()).build())
                .collect(Collectors.toList());
        try {
            BulkResponse bulkResponse = elasticsearchClient.bulk(new BulkRequest.Builder().operations(bulkOperations).build());
            if (bulkResponse.errors()) {
                System.out.println("Bulk operation had errors:");
                bulkResponse.items().forEach(item -> {
                    if (item.error() != null) {
                        System.out.println("Error for item with ID " + item.id() + ": " + item.error().reason());
                    }
                });
            } else {
                System.out.println("Bulk operation succeeded.");
//                for (BulkResponseItem item : bulkResponse.items()) {
//                    System.out.println("Indexed document with ID: " + item.id());
//                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    /**
     * {
     *   "size": 50,
     *   "query": {
     *     "bool": {
     *       "should": [
     *         {
     *           "match": {
     *             "title": "iPhone 11"
     *           }
     *         },
     *         {
     *           "match": {
     *             "model_name": "iPhone 11"
     *           }
     *         }
     *       ]
     *     }
     *   }
     * }
     * @param content 搜索关键词
     * @param pageable 分页参数
     * @return List<Tuple<String, Double>> 每个元素是 (产品 ID, 匹配分数) 构成的 Tuple
     * @throws IOException
     */
    public List<Tuple<String, Double>> searchByContent(String content, Pageable pageable) throws IOException {
        BoolQuery boolQuery = QueryBuilders.bool()
                .should(List.of(QueryBuilders.match(m -> m.field("title").query(content)),
                        QueryBuilders.match(m -> m.field("model_name").query(content))))
                .build();
        SearchResponse<ProductIndex> searchResponse = elasticsearchClient.search(s -> s
                .index(productIndexName).query(
                        q -> q.bool(boolQuery)
                ).size(pageable.getPageSize())
                .source(v -> v.fetch(false)), ProductIndex.class);
        HitsMetadata<ProductIndex> hits = searchResponse.hits();
        return hits.hits()
                .stream()
                .map(t ->
                new Tuple<>(t.id(), t.score()))
                .toList();
    }
}
