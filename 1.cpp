#include<bits/stdc++.h>
using namespace std;
#define ll long long

// 某种传染病第一天只有一个患者，
// 前5天为潜伏期，不发作也不会传染人，
// 第6天开始发作，从发作到治愈需要5天时间，
// 期间每天传染3个人，求第N天共有多少患者。

//潜伏期第i天的人数 n1[i]，总人数sum1
//发作期第i天的人数 n2[i], 总人数sum2
//每天传染 sum2 * 3个人


ll solve(ll day, ll* n1, ll* n2, ll n, ll sum1, ll sum2) {
	// 更新潜伏期人数
	sum2 -= n2[5];
	for (int i = 5; i > 1; i--)n2[i] = n2[i - 1];
	n2[1] = n1[5];
	sum2 += n2[1];
	// 更新发作期人数
	sum1 -= n1[5];
	for (int i = 5; i > 1; i--)n1[i] = n1[i - 1];
	n1[1] = sum2 * 3;
	sum1 += n1[1];
	if (day == n)return sum1 + sum2;
	// 递归调用
	return solve(day + 1, n1, n2, n, sum1, sum2);
}

int main() {
	ll n; cin >> n;
	ll n1[6] = { 0 }; // 潜伏期人数
	n1[1] = 1; // 第一天有一个患者
	ll ans = solve(2, n1, new ll[6]{0}, n, 1, 0);
	cout << ans;
	return 0;
}