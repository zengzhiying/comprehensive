<?php
$socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP) or die ('could not create socket');
$host = '127.0.0.1';
$connect = socket_connect($socket, $host, 8080);
$socket_array = array(
    'name' => "zzy",
    'number_id' => "02" 
    );
$socket_json = json_encode($socket_array);
socket_write($socket, $socket_json."\n");
//接受服务端返回数据 
$out = socket_read($socket, 1024, PHP_NORMAL_READ);
//关闭 socket
socket_close($socket);
echo $out;
?>