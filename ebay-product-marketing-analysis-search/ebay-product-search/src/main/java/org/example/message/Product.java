package org.example.message;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import lombok.Data;


@Data
@Entity
@Table(name = "product")
public class Product {
    @NotBlank(message = "uniqId is required")
    @NotNull
    @Id
    @Column(name = "uniq_id", nullable = false, length = 32)
    private String uniqId;           // 全局唯一ID
    @NotBlank(message = "crawlTimestamp is required")
    @Pattern(regexp = "\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}",
            message = "Invalid crawlTimestamp format")
    @Column(name = "crawl_timestamp", nullable = false)
    private String crawlTimestamp;   // 爬取时间，格式为：yyyy-MM-dd HH:mm:ss
    @NotBlank(message = "pageUrl is required")
    @Column(name = "page_url", nullable = false)
    private String pageUrl;          // 产品页面URL
    @NotBlank(message = "title is required")
    @Column(name = "title", nullable = false)
    private String title;            // 产品标题
    @NotBlank(message = "modelNum is required")
    @Column(name = "model_num", nullable = false)
    private String modelNum;         // 产品型号
    @NotBlank(message = "manufacturer is required")
    @Column(name = "manufacturer", nullable = false)
    private String manufacturer;     // 厂商名称
    @NotBlank(message = "modelName is required")
    @Column(name = "model_name", nullable = false)
    private String modelName;        // 产品名称
    @NotBlank(message = "price is required")
    @Column(name = "price", nullable = false)
    private String price;            // 价格
    @NotNull
    @Column(name = "stock", nullable = false)
    private Integer stock;           // 是否有库存（0: 无，1: 有）
    @NotBlank(message = "carrier is required")
    @Column(name = "carrier", nullable = false)
    private String carrier;          // 运营商（如AT&T）
    @NotBlank(message = "colorCategory is required")
    @Column(name = "color_category", nullable = false)
    private String colorCategory;    // 颜色分类
    @NotBlank(message = "internalMemory is required")
    @Column(name = "internal_memory", nullable = false)
    private String internalMemory;   // 内存配置（如 64 GB）
    @NotBlank(message = "screenSize is required")
    @Column(name = "screen_size", nullable = false)
    private String screenSize;       // 屏幕尺寸（如 6.7 in）
    @NotNull
    @Column(name = "discontinued", nullable = false)
    private Integer discontinued;    // 是否停售（0: 未停售，1: 停售）
    @NotNull
    @Column(name = "broken_link", nullable = false)
    private Integer brokenLink;      // 链接是否失效（0: 未失效，1: 失效）
    @NotNull
    @Column(name = "seller_rating", nullable = false)
    private Double sellerRating;     // 卖家评分
    @NotNull
    @Column(name = "seller_num_of_reviews", nullable = false)
    private Integer sellerNumOfReviews; // 卖家评价数量
    @NotNull
    @Column(name = "average_star", nullable = false)
    private Double averageStar;      // 平均评分
}
