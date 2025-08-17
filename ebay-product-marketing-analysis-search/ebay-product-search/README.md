# Spring Boot 搜索服务

## 服务接口设计

### 1. 产品写入服务
路由和方法：`POST /api/product`

请求 Body 为完整的 JSON 消息。

请求成功返回：

```json
{"message": "Data sent to Kafka successfully"}
```

### 2. 产品搜索服务
路由和方法：`GET /api/product/search`

参数类型: Query String

参数定义如下：

| 参数名          | 含义                            |
|--------------|-------------------------------|
| manufacturer | 品牌名搜索，和 `content` 参数互斥        |
| content      | 按照关键词搜索，和 `manufacturer` 参数互斥 |

参数 `manufacturer` 和 `content` 至少存在 1 个。

查询返回 JSON Array，每个元素为一个商品的 Object。

### 3. 产品详情查询
路由和方法：`GET /api/product/{id}`

参数类型：Path String（参数在路由中 `{id}` 表示变量）

参数定义如下：

| 参数名 | 含义      |
|-----|---------|
| id  | 产品唯一 ID |

查询成功返回产品的 JSON Object，产品不存在返回 HTTP Code 404

### 4. 评论数量排行榜
路由和方法：`GET /api/product/review-ranking`

该请求不需要参数。

查询成功返回 JSON Array，每个元素为一个商品的 Object。

### 5. 品牌数量排行榜
路由和方法：`GET /api/product/brand-ranking`

该请求不需要参数。

查询成功返回 JSON Array，格式示例如下：

```json
[{"key": "Apple", "score": 10121}, {"key": "Google", "score": 9899}]
```

其中每个 Object 的 `key` 表示品牌，`score` 表示品牌下的数量。

