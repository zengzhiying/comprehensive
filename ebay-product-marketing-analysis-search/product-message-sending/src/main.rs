mod product;

use std::sync::{atomic, Arc};

use product::Product;
use tokio::{task, time::Instant};
#[tokio::main]
async fn main() {
    let concurrency = 1000;
    let produce_num = atomic::AtomicU64::new(0);
    let produce_num = Arc::new(produce_num);
    let produce_num_clone = produce_num.clone();
    let (tx, rx) = async_channel::bounded(100);
    let producer = task::spawn_blocking(move || {
        let csv_file = "ebay-product.csv";
        let csv_content: String = std::fs::read_to_string(csv_file).expect("Failed to read CSV file");
        let mut reader = csv::Reader::from_reader(csv_content.as_bytes());
        for record in reader.deserialize() {
            let mut row: Product = record.expect("Failed to deserialize CSV record");
            row.remove_timezone_suffix();
            let message = serde_json::to_string(&row).expect("Failed to serialize to JSON");
            // println!("{}", message);
            tx.send_blocking(message).expect("Failed to send message");
            produce_num_clone.fetch_add(1, atomic::Ordering::Relaxed);
            // if num == 20 {
            //     break;
            // }
        }
        println!("Producer finished, total: {}", produce_num_clone.load(atomic::Ordering::Relaxed));
    });
    println!("Producer started");
    let client = reqwest::Client::new();

    let mut consumers = vec![];
    for i in 0..concurrency {
        let rx = rx.clone();
        let client = client.clone();
        let consumer = task::spawn(async move {
            let mut num = 0;
            loop {
                let res = rx.recv().await;
                match res {
                    Ok(message) => {
                        let resp_result = client.post("http://localhost:18081/api/product")
                            .body(message)
                            .header("Content-Type", "application/json")
                            .send().await;
                        if let Err(err) = resp_result {
                            println!("Task {} failed to send message: {}", i, err);
                            continue;
                        }
                        let resp = resp_result.unwrap();
                        if resp.status() != 200 {
                            println!("Task {} failed to send message: {}", i, resp.status());
                            continue;
                        }
                        num += 1;
                    }
                    Err(err) => {
                        println!("Task {} received error: {}", i, err);
                        break;
                    }
                }
            }
            
            println!("Task {} Consumer {} finished", i, num);
        });
        consumers.push(consumer);
    }

    println!("Consumers started");
    // 获得当前时间戳
    let start_time = Instant::now();

    producer.await.expect("Failed to run producer");
    println!("Producer finished");
    for consumer in consumers {
        consumer.await.expect("Failed to run consumer");
    }

    let end_time = Instant::now();
    let elapsed_time = end_time - start_time;
    println!("All tasks finished total time: {}ms QPS: {}", elapsed_time.as_millis(), produce_num.load(atomic::Ordering::Relaxed) / elapsed_time.as_secs());
    
}

