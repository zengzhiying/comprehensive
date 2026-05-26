---
title: JSON 规范化方案
tags:
  - json
created_time: 2026-01-21
synced:
synced_time:
modified_time: 2026-01-26
---
# JSON 规范化方案

在开发中发现对于同样的来源的 JSON 字符串在 Java 中解析后再编码和 Python 中解析后再编码生成的结果字符串可能是不一样的。这种情况正常是没有什么问题的，但是对于需要用 JSON 生成散列并需要校验的场景，对于 JSON 的生成有着严格的要求，也就是对于相同语义的 JSON 表达，序列化后的结果字节必须完全一致才满足需要，而大多数 JSON 库都无法比较好地实现跨语言的一致性保证。

这种情况下一种比较直接的方案就是私有编码，例如按照一致的字段顺序以及结果值的底层字节进行二进制编码，保证结果的稳定性。但是这种方法需要针对业务进行开发，不好扩展而且难于调试，容易出现错误。这时候就比较推荐另一种公开的方案 [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)，方案全名就是 JSON Canonicalization Scheme (JCS)，基于这种方案可以实现 JSON 跨平台交换的一致性，可以用在比较严格的场景下。

JCS 的官方实现仓库为 [https://github.com/cyberphone/json-canonicalization](https://github.com/cyberphone/json-canonicalization)

目前支持 Rust、Java、Go、Python、PHP 等多种语言的实现，例如 Java 的实现为 [https://github.com/erdtman/java-json-canonicalization](https://github.com/erdtman/java-json-canonicalization)、Python 的实现就在主仓库下为 [https://github.com/cyberphone/json-canonicalization/tree/master/python3](https://github.com/cyberphone/json-canonicalization/tree/master/python3)

在 Java Maven 项目中使用目前可以导入依赖如下：

```xml
<dependency>
  <groupId>io.github.erdtman</groupId>
  <artifactId>java-json-canonicalization</artifactId>
  <version>1.1</version>
</dependency>
```

使用也是很简单，比如：

```java
String json = "xxx";
JsonCanonicalizer jc = new JsonCanonicalizer(json);
System.out.println(jc.getEncodedString());
```

而 Python 的实现目前并没有提供 pip 方式的安装，可以直接导入源文件的路径使用，也可以直接安装另外一个叫做 [jcs](https://pypi.org/project/jcs/) 的库，这个库的仓库地址是 [https://github.com/titusz/jcs](https://github.com/titusz/jcs)。这个仓库其实就是搬运的上面官方仓库的 Python 代码，只是通过 pyproject 的方式制作了分发包，方便进行安装。所以我们可以直接安装使用：

```shell
pip3 install jcs
```

直接传入字典即可：

```python
import json
import jcs

json = 'xxx'
data = jcs.canonicalize(json.loads(json))
print(data.decode())
```

目前这个库最新版比官方的代码旧了一些，但是测试了各种 JSON 输入，生成的结果都没有问题，仍然是可以考虑使用的。

另外还有一个 [rfc8785.py](https://github.com/trailofbits/rfc8785.py) 的仓库，这个也是基于官方的源码进行了单文件封装，并且在官方的基础上做了一些增强，但是具体没有详细验证，后续也可以尝试使用。

有了上述的这些实现，就可以保证 Java 和 Python 生成 JSON 的结果完全一致，可以在散列校验等严格的场景中使用。



