package org.example.message;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class ProductRanking {
    private String key;
    private Long score;
}
