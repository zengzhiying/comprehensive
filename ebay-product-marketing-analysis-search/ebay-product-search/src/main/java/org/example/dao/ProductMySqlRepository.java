package org.example.dao;

import org.example.message.Product;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface ProductMySqlRepository extends JpaRepository<Product, String> {
    @Query("SELECT p FROM Product p " +
            "WHERE p.manufacturer = :manufacturer " +
            "AND p.stock = 1 " +
            "AND p.discontinued = 0 " +
            "AND p.brokenLink = 0 " +
            "ORDER BY p.averageStar DESC")
    Page<Product> findAvailableProductsByManufacturer(@Param("manufacturer") String manufacturer,
                                                      Pageable pageable);

    @Query("SELECT p FROM Product p WHERE p.uniqId IN :ids " +
            "AND p.stock = 1 " +
            "AND p.discontinued = 0 " +
            "AND p.brokenLink = 0 ")
    Page<Product> findAvailableProductsByIds(
            @Param("ids") List<String> ids,
            Pageable pageable);
}

