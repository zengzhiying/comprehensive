package org.example.message;

import lombok.AllArgsConstructor;
import lombok.Data;
import org.springframework.data.annotation.Id;
import org.springframework.data.elasticsearch.annotations.Document;
import org.springframework.data.elasticsearch.annotations.Field;
import org.springframework.data.elasticsearch.annotations.FieldType;

@Data
@AllArgsConstructor
@Document(indexName = "product_index")
public class ProductIndex {
    @Id
    private String uniqId;
    @Field(type = FieldType.Text, name = "title")
    private String title;            // 产品标题
    @Field(name = "model_name", type = FieldType.Text)
    private String modelName;        // 产品名称
}
