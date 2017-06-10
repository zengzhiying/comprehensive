package net.zengzhiying;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;

public class SocketServer {
	private static ServerSocket serverSocket = null;
	public static void main(String[] args) {
		try {
			serverSocket = new ServerSocket(8080);
			System.out.println("socket创建成功...");
		} catch (IOException e) {
			System.out.println("socket创建失败...");
			e.printStackTrace();
		}
		if(serverSocket != null) {
			while(true) {
				try {
					Socket client = serverSocket.accept();
					PrintWriter printer = new PrintWriter(client.getOutputStream());
					BufferedReader reader = new BufferedReader(new InputStreamReader(client.getInputStream()));
					
					String m = reader.readLine();
					System.out.println("获取到来自客户端的信息为:" + m);
					String result = m;
					// 处理客户端信息 比如转为对象等
					//RequestBean requestbean = new Gson().fromJson(m, RequestBean.class);
					//System.out.println(requestbean.toString());
					// 然后执行一些逻辑
					//String result = CreateThreadService.getDataResult();
					// 回传给客户端
					printer.println(result);
					printer.flush();
					printer.close();
					client.close();
					System.out.println("客户端请求完毕...");
				} catch (IOException e) {
					System.out.println("创建client失败..");
					e.printStackTrace();
				}
				
			}
		}
	}
}
