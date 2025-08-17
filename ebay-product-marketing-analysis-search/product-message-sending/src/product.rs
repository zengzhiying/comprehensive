use serde::{Deserialize, Serialize, Serializer};


#[derive(Debug, Deserialize)]
pub struct Product {
    pub uniq_id: String,
    pub crawl_timestamp: String,
    pub page_url: String,
    pub title: String,
    pub model_num: String,
    pub manufacturer: String,
    pub model_name: String,
    pub price: String,
    pub stock: i8,
    pub carrier: String,
    pub color_category: String,
    pub internal_memory: String,
    pub screen_size: String,
    pub discontinued: i8,
    pub broken_link: i8,
    pub seller_rating: f64,
    pub seller_num_of_reviews: i32,
    pub average_star: f64,
}

fn serialize_as_camel_case<S>(product: &Product, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    use serde::ser::SerializeStruct;
    let mut state = serializer.serialize_struct("Product", 18)?;
    state.serialize_field("uniqId", &product.uniq_id)?;
    state.serialize_field("crawlTimestamp", &product.crawl_timestamp)?;
    state.serialize_field("pageUrl", &product.page_url)?;
    state.serialize_field("title", &product.title)?;
    state.serialize_field("modelNum", &product.model_num)?;
    state.serialize_field("manufacturer", &product.manufacturer)?;
    state.serialize_field("modelName", &product.model_name)?;
    state.serialize_field("price", &product.price)?;
    state.serialize_field("stock", &product.stock)?;
    state.serialize_field("carrier", &product.carrier)?;
    state.serialize_field("colorCategory", &product.color_category)?;
    state.serialize_field("internalMemory", &product.internal_memory)?;
    state.serialize_field("screenSize", &product.screen_size)?;
    state.serialize_field("discontinued", &product.discontinued)?;
    state.serialize_field("brokenLink", &product.broken_link)?;
    state.serialize_field("sellerRating", &product.seller_rating)?;
    state.serialize_field("sellerNumOfReviews", &product.seller_num_of_reviews)?;
    state.serialize_field("averageStar", &product.average_star)?;
    state.end()
}

impl Serialize for Product {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serialize_as_camel_case(self, serializer)
    }
}

impl Product {
    pub fn remove_timezone_suffix(&mut self) {
        match self.crawl_timestamp.rfind(" ") {
            Some(index) => {
                self.crawl_timestamp = self.crawl_timestamp[..index].to_string();
            }
            None => panic!("Failed to remove timezone suffix from crawl_timestamp: {}", self.crawl_timestamp)
            
        }
    }
}
