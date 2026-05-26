---
title: Rust 中使用编译脚本 build.rs 生成 Protobuf 代码的用法
synced:
synced_time:
tags:
  - rust
  - protobuf
  - tonic
created_time: 2026-03-17
modified_time: 2026-03-18
---

我们知道在使用 Protobuf 时需要根据 `.proto` 文件的结构定义生成对应编程语言的结构定义，然后才可以在代码中调用。而这个生成过程可以放到 Rust 的构建脚本中，下面就以 Protobuf 中使用 `build.rs` 生成 Rust 代码为例进行用法的说明。

主要就是说明在项目中 `build.rs` 的作用，以及 `.proto` 文件是如何在编译阶段被转换为 Rust 代码，再和业务代码结合起来使用的。

## 1. `build.rs` 的作用

`build.rs` 是 Cargo 的构建脚本，也可以理解为“编译前执行的小程序”。

它有几个重要特点：

1. 它不是运行时程序的一部分
2. 它不是通过 `cargo run` 直接运行的
3. 它会在 Cargo 正式编译项目源码之前自动执行
4. 它使用的是 `[build-dependencies]`，而不是普通的 `[dependencies]`

所以项目里 `src/main.rs` 负责启动主程序，`build.rs` 负责在编译前做一些预处理，比如生成 protobuf / gRPC 对应的 Rust 代码。

## 2. `build.rs` 的运行时机

只要执行下面这些 Cargo 命令，Cargo 都会先处理 `build.rs`：

```bash
cargo build
cargo run
cargo test
cargo check
```

大致流程如下：

1. Cargo 解析 `Cargo.toml`
2. Cargo 编译 `build.rs`
3. Cargo 运行 `build.rs`
4. `build.rs` 生成中间代码或输出构建指令
5. Cargo 再编译 `src/lib.rs` 和 `src/main.rs` 等正式源码
6. 完成链接并生成可执行文件或测试程序

因此，`build.rs` 永远发生在“编译业务代码之前”。

## 3. `build.rs` 使用示例

例如 `build.rs` 内容如下：

```rust
fn main() {
    println!("cargo:rerun-if-changed=proto/uploading/v1/file_upload.proto");

    let protoc = protoc_bin_vendored::protoc_bin_path()
        .expect("failed to fetch vendored protoc binary path");
    unsafe {
        std::env::set_var("PROTOC", protoc);
    }

    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .compile_protos(&["proto/uploading/v1/file_upload.proto"], &["proto"])
        .expect("failed to compile protobuf definitions");
}
```

它实际完成三件事：

1. 告诉 Cargo 如果 `file_upload.proto` 发生变化，就重新执行构建脚本
2. 为 Protobuf 编译器准备一个可用的 `protoc`
3. 调用 `tonic_build` 把 `.proto` 编译成 Rust 代码

`build.rs` 中 `println!` 输出到标准输出的内容，不只是打印内容。如果某一行以 `cargo:` 开头，Cargo 会把它当成构建指令来解析，这是构建脚本和 Cargo 之间的通信方式。

例如当前的：

```rust
println!("cargo:rerun-if-changed=proto/uploading/v1/file_upload.proto");
```

它的意思是告诉 Cargo 监听这个 proto 文件，当这个文件内容发生变化时下次构建必须重新执行 `build.rs`。如果没有这句，Cargo 可能会直接复用旧的构建结果，导致改了 `.proto` 但生成的代码没有更新。比如有时候我们改了 `.proto` 但代码没变化就需要优先检查 `build.rs` 是否声明了 `cargo:rerun-if-changed=...`

常见的 Cargo 构建指令还有：

1. `cargo:rerun-if-changed=...`
2. `cargo:rerun-if-env-changed=...`
3. `cargo:rustc-env=KEY=VALUE`
4. `cargo:rustc-link-lib=...`
5. `cargo:rustc-link-search=...`

所以可以把 `build.rs` 理解成普通 Rust 程序通过 Stdout 向 Cargo 发送构建指令。

然后就是要设置 `PROTOC`，`tonic_build` 和 `prost-build` 在编译 `.proto` 文件时，底层依赖 `protoc` 来实现解析和翻译。

默认情况下，它们会尝试在系统环境中查找 `protoc` 命令，但如果宿主机没有安装 protobuf 编译器就会失败，报错如 `Could not find protoc`，所以我们可以通过 `protoc-bin-vendored` 直接使用 Rust 构建依赖，从而避免了对系统环境的依赖：

```rust
let protoc = protoc_bin_vendored::protoc_bin_path()
    .expect("failed to fetch vendored protoc binary path");
unsafe {
    std::env::set_var("PROTOC", protoc);
}
```

这段代码的含义是从 vendored 包里找到一个可用的 `protoc` 路径，然后把它设置到当前进程的环境变量 `PROTOC`，后续 `tonic_build` 就会优先使用这个路径，而不是依赖系统全局安装。

这样做的好处就是开发者不需要手动安装 `protobuf-compiler`，可以用在 CI 场景下保证新环境拉起时更稳定，避免我们的本机能编译而别人的机器不能编译的问题。

另外还要注意 `set_var` 要写在 `unsafe` 里，这是 Rust 2024 的行为变化。

主要由于 `std::env::set_var` 修改的是进程级全局环境变量。在多线程或复杂构建场景下，这种全局修改存在潜在风险，因此在新版本里被标记成了 `unsafe`。

所以需要写成：

```rust
unsafe {
    std::env::set_var("PROTOC", protoc);
}
```

这个意思不代表这段代码一定危险，而是表示这是一次对全局进程环境的修改，调用者需要显式承担这件事的语义责任。

当然在当前 `build.rs` 里，这样写是完全合理的，因为构建脚本进程生命周期很短而且变量只为本次构建中的 `tonic_build` 调用使用，没有任何其他的副作用。

最后会调用 `compile_protos` 来执行编译，当前代码为：

```rust
.compile_protos(&["proto/uploading/v1/file_upload.proto"], &["proto"])
```

其中第一个参数表示要编译哪些 `.proto` 文件，路径需要完整。

第二个参数表示 `.proto` 生成结构体的的 include 根目录，当 `.proto` 中存在 `import` 时，从哪些根目录查找依赖，例如未来我们添加 `import "uploading/v1/common.proto";`，那么 `&["proto"]` 就表示从 `proto/` 下面开始找，实际会去定位 `proto/uploading/v1/common.proto`，就可以正常找到依赖了。

然后就是代码：

```rust
tonic_build::configure()
    .build_server(true)
    .build_client(false)
```

这部分意思是生成服务端需要的 gRPC 代码但不生成客户端代码。

比如下面的服务定义：

```protobuf
service UploadService {
  rpc Upload(UploadRequest) returns (UploadResponse);
}
```

对于服务端只需要生成 `UploadService` trait 以及 `UploadServiceServer<T>` 结构体即可。

假如我们在项目中还要内置 gRPC 客户端调用代码，可以改为：

```rust
.build_client(true)
```

这样就会额外生成 client stub。

## 4. 代码生成的位置

`tonic_build` / `prost-build` 不会把生成代码写回 `src/`，而是会写到 Cargo 的构建输出目录中，也就是 `OUT_DIR`。

通常会类似 `target/debug/build/<pkg>/out/`，里面会有类似 `uploading.v1.rs` 的源文件。

之所以不写入 `src/`，主要有下面的原因：

1. 保持源码目录干净
2. 避免把生成物误提交到 Git
3. debug/release 和不同 target 可以拥有各自独立的生成产物
4. 便于 Cargo 管理缓存

`OUT_DIR` 是 Cargo 在构建阶段提供的环境变量，`tonic_build` 和 `prost-build` 会把生成文件写到这里。虽然在 `build.rs` 没有手动读取 `OUT_DIR`，但其内部依赖已经在使用它，实际的流程图下：

```
build.rs
-> tonic_build::compile_protos(...)
-> tonic/prost 内部读取 OUT_DIR 环境变量
-> 生成 uploading.v1.rs 到 OUT_DIR
```

我们可以通过编译时确定代码是否正常生成到指定位置，例如：

```bash
# 清空缓存后构建
cargo clean
cargo build -vv
```

使用 `cargo build -vv` 会输出更详细的构建日志。


## 5. 引用生成的代码

我们可以在项目代码中引用生成的代码，比如：

```rust
pub mod uploading {
    pub mod v1 {
        tonic::include_proto!("uploading.v1");
    }
}
```

`include_proto!("uploading.v1")` 可以理解成在编译期包含生成代码的宏。逻辑上其实等同于下面的代码：

```rust
include!(concat!(env!("OUT_DIR"), "/uploading.v1.rs"));
```

意思表示在编译时读取 `OUT_DIR` 并找到生成好的 `uploading.v1.rs`，然后把它插入到当前模块中。

然后项目里其他代码可以通过统一路径访问生成的类型，例如：

1. `crate::proto::uploading::v1::UploadRequest`
2. `crate::proto::uploading::v1::UploadResponse`
3. `crate::proto::uploading::v1::upload_service_server::UploadService`

## 6. `.proto` 到 Rust 的常见对应关系

### 6.1. `message -> Rust struct`

我们在 `.proto` 中定义的 `message` 对象会映射到 Rust 中的结构体 `struct`，例如下面的对象：

```protobuf
message UploadRequest {
  string dtype = 1;
  uint32 dim = 2;
  repeated float vectors = 3;
  bytes flat_ids = 4;
  bool auto_set = 5;
  UploadOptions options = 6;

  string request_id = 7;
  map<string, string> tags = 8;
}
```

Protobuf 到 Rust 的字段映射关系如下：

1. `string -> String`
2. `uint32 -> u32`
3. `bool -> bool`
4. `bytes -> Vec<u8>`
5. `repeated float -> Vec<f32>`
6. `map<string, string> -> HashMap<String, String>`
7. 嵌套 message -> 对应 Rust struct 或 `Option<T>`

### 6.2. `enum -> Rust enum`

比如下面的定义：

```protobuf
syntax = "proto3";
package chat;

enum UserStatus {
  OFFLINE = 0;
  ONLINE = 1;
  AWAY = 2;
}

message User {
  string name = 1;
  UserStatus status = 2;
}
```

Protobuf 中要求枚举的第一个成员必须是 0，在执行 `tonic_build` 后生成的代码大致如下：

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)]
#[repr(i32)]
pub enum UserStatus {
    Offline = 0,
    Online = 1,
    Away = 2,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct User {
    #[prost(string, tag = "1")]
    pub name: ::prost::alloc::string::String,
    #[prost(enumeration = "UserStatus", tag = "2")]
    pub status: i32,
}
```

需要注意的是结构体中嵌套的枚举会生成 `i32` 类型的字段，在使用时需要进行转换，不过`prost` 给我们提供了方便的转换方法。

如果是发送端写法比较简单，例如：

```rust
let user = User {
    name: "Gemini".to_string(),
    status: UserStatus::Online as i32, // 使用 as i32 转换
};
```

如果是在服务端接收可以通过 `from_i32` 方法转换到枚举然后再匹配，例如：

```rust
match UserStatus::from_i32(user.status) {
    Some(UserStatus::Online) => println!("用户在线"),
    Some(UserStatus::Offline) => println!("用户离线"),
    Some(UserStatus::Away) => println!("离开"),
    None => println!("未知的状态值: {}", user.status)
}
```

还要注意生成的枚举名和 `.proto` 里的枚举名不完全一致的问题，假如枚举名称我们可能会定义为 `ONLINE_STATUS`，那么 `prost` 可能会将命名按照 Rust 风格转换为驼峰方式，生成后通常会变成 `UserStatus::OnlineStatus`，所以遇到枚举名称找不到时最好直接看生成后的源文件或者依赖开发环境的提示编写。

### 6.3. `service -> trait + server 包装器`

例如上面提到的 `upload_service_server::UploadService` 和 `VectorClusteringServiceServer<T>`。前者是 trait 我们要在代码中实现它的方法，实际运行服务时会进行调用，而后面这个结构体主要就是承载 gRPC 服务的输入 Protobuf 请求数据解码以及相应数据编码等工作。

## 7. 服务端使用生成的代码

### 7.1. 实现 gRPC trait

可以在 `services.rs` 中实现生成的 train：

```rust
pub struct UploadGrpcService;

impl UploadService for UploadGrpcService {
    async fn upload(
        &self,
        request: Request<UploadRequest>,
    ) -> Result<Response<UploadResponse>, Status> {
        Ok(Response::new(upload::execute_upload(
            request.into_inner(),
        )))
    }
}
```

上面的示例中 `VectorClusteringService` trait 是自动生成的，我们只需要实现其中的 `upload` 方法。并且请求已经被 Tonic 自动解码成 `UploadRequest` 结构体，而且响应只要返回 Rust 的 `ClusterResponse`，Tonic 会自动重新编码成 Protobuf，业务层只需要实现自己的逻辑即可。

我们这里定义了结构体 `UploadGrpcService`，这个结构体没有属性也叫做单元结构体，只是为了承载 trait 的实现。但是假如我们要在 gRPC 服务中共享全局的属性，可以根据我们的业务定义属性。比如：

```rust
pub struct UploadGrpcService {
	service_name: &'static str,
	request_semaphore: Arc<Semaphore>,
}

impl UploadGrpcService {
    pub fn new() -> Self {
        Self {
            service_name: "upload service",
            request_semaphore: Arc::new(Semaphore::new(32)),
        }
    }
}

impl Default for UploadGrpcService {
    fn default() -> Self {
        Self::new()
    }
}
```

这样我们就能在 `upload` 方法中通过 `self.` 的方式引用定义的属性了，在所有的并发请求中属性是共享的。

### 7.2. 注册 gRPC server

我们可以在 `main` 中初始化 gRPC 服务如下：

```rust
let grpc_service = UploadGrpcService::default();
Server::builder()
    .add_service(
        UploadServiceServer::new(grpc_service)
            .max_decoding_message_size(128*1024*1024)
            .max_encoding_message_size(128*1024*1024)
    )
    .serve(grpc_addr)
    .await;
```

这里的 `UploadServiceServer` 也是自动生成的，主要负责接收 gRPC 请求并按 Protobuf 协议解码数据，然后找到对应 RPC 方法，比如调用我们在 `service.rs` 中实现的 `upload`，最后把返回结果重新编码为 Protobuf 响应。

可以看到 gPRC 的协议处理和 Protobuf 结构解析这部分都由 Tonic 和 Prost 自动完成，我们只需要对结构体进行业务处理然后按照约定返回响应的结构，最后的 Protobuf 编码和 gRPC 响应传输也是由框架自动处理的。

## 8. 最后总结下完整链路

我们把从 `build.rs` 生成结构到项目引用代码再到实际执行这整个过程概括成下面的链路：

```
定义 file_upload.proto
-> build.rs 调 tonic_build/prost 生成 Rust 代码并写入 OUT_DIR
-> src/proto.rs 通过 include_proto! 引入生成代码
-> src/service.rs 实现自动生成的 gRPC trait
-> src/main.rs 注册自动生成的 Server
-> Tonic 把请求解码成 Rust 结构体
-> 业务层在实现的方法中执行具体的逻辑
-> 返回响应结构体
-> Tonic 再把响应编码成 Protobuf 发回客户端
```


参考链接：[https://doc.rust-lang.org/cargo/reference/build-scripts.html](https://doc.rust-lang.org/cargo/reference/build-scripts.html)

