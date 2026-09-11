# ch01 随机事件与概率

## 样本空间与事件

随机试验 E 的所有可能结果构成的集合称为**样本空间**，记作 $\Omega$。
样本空间的元素称为**样本点** $\omega$。事件是样本空间的子集 $A \subseteq \Omega$。

- 必然事件：$\Omega$；不可能事件：$\varnothing$。
- 事件的关系：包含 $A \subset B$、相等、互斥（$AB=\varnothing$）、对立（$A\bar A=\varnothing$ 且 $A\cup\bar A=\Omega$）。
- De Morgan 律：$\overline{A\cup B}=\bar A\bar B$，$\overline{AB}=\bar A\cup\bar B$。

## 概率的公理化定义与性质

概率 $P(\cdot)$ 是定义在事件域上的集函数，满足：
1. 非负性：$P(A)\ge 0$；
2. 规范性：$P(\Omega)=1$；
3. 可列可加性：若 $A_i$ 两两互斥，则 $P\left(\bigcup_{i=1}^{\infty}A_i\right)=\sum_{i=1}^{\infty}P(A_i)$。

由公理可得：
- $P(\varnothing)=0$
- $P(\bar A)=1-P(A)$
- **加法公式**：$P(A\cup B)=P(A)+P(B)-P(AB)$
- 若 $A\subset B$，则 $P(B-A)=P(B)-P(A)$ 且 $P(A)\le P(B)$

## 古典概型与几何概型

**古典概型**（等可能有限样本空间）：
$$P(A)=\frac{\text{有利于 }A\text{ 的样本点数}}{\text{样本点总数}}=\frac{|A|}{|\Omega|}$$
计数依赖排列组合：$A_n^m=\dfrac{n!}{(n-m)!}$，$C_n^m=\dfrac{n!}{m!(n-m)!}$。

**几何概型**（等可能无限样本空间，用测度比）：
$$P(A)=\frac{\mu(A)}{\mu(\Omega)}$$
例如布丰投针问题用长度/面积比估计 $\pi$。

## 条件概率

当 $P(B)>0$ 时，在事件 $B$ 已发生的条件下事件 $A$ 发生的**条件概率**为：
$$P(A\mid B)=\frac{P(AB)}{P(B)}$$

注意 $P(A\mid B)$ 与 $P(B\mid A)$ 方向不同，不可混淆。

**乘法公式**：
$$P(AB)=P(B)P(A\mid B)=P(A)P(B\mid A)$$
推广：$P(A_1A_2\cdots A_n)=P(A_1)P(A_2\mid A_1)\cdots P(A_n\mid A_1\cdots A_{n-1})$。

## 全概率公式与贝叶斯公式

设 $B_1,B_2,\dots,B_n$ 为**完备事件组**（两两互斥，且 $\bigcup_i B_i=\Omega$，$P(B_i)>0$）。

**全概率公式**（由因求果）：
$$P(A)=\sum_{i=1}^{n}P(B_i)P(A\mid B_i)$$

**贝叶斯公式**（由果推因，先验 + 似然 → 后验）：
$$P(B_i\mid A)=\frac{P(B_i)P(A\mid B_i)}{\sum_{j=1}^{n}P(B_j)P(A\mid B_j)}$$

其中 $P(B_i)$ 是**先验概率**，$P(A\mid B_i)$ 是**似然**，$P(B_i\mid A)$ 是**后验概率**。

## 事件的独立性

若 $P(AB)=P(A)P(B)$，称 $A$ 与 $B$ **相互独立**。
注意：**独立 ≠ 互斥**。若 $P(A)>0,P(B)>0$ 且互斥，则一定不独立。

$n$ 个事件相互独立要求任意 $k$ 个的交事件概率等于各自概率之积。

# ch02 随机变量与分布

## 随机变量与分布函数

**随机变量** $X$ 是定义在 $\Omega$ 上、取值于实数的函数。
**分布函数**：
$$F(x)=P(X\le x),\quad x\in\mathbb R$$
性质：单调不减、右连续、$F(-\infty)=0$、$F(+\infty)=1$。

## 离散型随机变量

取值可列的 $X$，其**分布律** $p_k=P(X=x_k)$ 满足 $\sum_k p_k=1$。

常见离散分布：
- **0-1 分布** $B(1,p)$：$E[X]=p$，$\mathrm{Var}(X)=p(1-p)$
- **二项分布** $B(n,p)$：$P(X=k)=C_n^k p^k(1-p)^{n-k}$，$E[X]=np$，$\mathrm{Var}(X)=np(1-p)$
- **泊松分布** $P(\lambda)$：$P(X=k)=\dfrac{\lambda^k e^{-\lambda}}{k!}$，$E[X]=\mathrm{Var}(X)=\lambda$
- **几何分布** $G(p)$：$P(X=k)=(1-p)^{k-1}p$，$E[X]=1/p$，$\mathrm{Var}(X)=(1-p)/p^2$，具有无记忆性

## 连续型随机变量

存在非负可积的**概率密度函数** $f(x)$ 使 $F(x)=\int_{-\infty}^{x}f(t)\,dt$，
且 $\int_{-\infty}^{+\infty}f(x)\,dx=1$。

常见连续分布：
- **均匀分布** $U(a,b)$：$f(x)=\dfrac{1}{b-a}$，$E[X]=\dfrac{a+b}{2}$，$\mathrm{Var}(X)=\dfrac{(b-a)^2}{12}$
- **指数分布** $Exp(\lambda)$：$f(x)=\lambda e^{-\lambda x}\ (x>0)$，$E[X]=1/\lambda$，$\mathrm{Var}(X)=1/\lambda^2$，无记忆性
- **正态分布** $N(\mu,\sigma^2)$：$f(x)=\dfrac{1}{\sqrt{2\pi}\sigma}e^{-\frac{(x-\mu)^2}{2\sigma^2}}$，$E[X]=\mu$，$\mathrm{Var}(X)=\sigma^2$
- **伽马分布** $Ga(\alpha,\beta)$：$E[X]=\alpha\beta$，$\mathrm{Var}(X)=\alpha\beta^2$
- **贝塔分布** $Be(\alpha,\beta)$：$E[X]=\dfrac{\alpha}{\alpha+\beta}$，$\mathrm{Var}(X)=\dfrac{\alpha\beta}{(\alpha+\beta)^2(\alpha+\beta+1)}$

## 随机变量函数的分布

已知 $X$ 的密度 $f_X$，求 $Y=g(X)$ 的密度。
- **单调可导**时用公式法：$f_Y(y)=f_X(h(y))\,|h'(y)|$，其中 $h=g^{-1}$。
- **非单调**时用分布函数法：先求 $F_Y(y)=P(g(X)\le y)$，再求导。

# ch03 多维随机变量

## 联合分布与边缘分布

二维随机变量 $(X,Y)$ 的**联合分布函数** $F(x,y)=P(X\le x, Y\le y)$。

**边缘分布函数**由联合分布函数取极限得到：
$$F_X(x)=F(x,+\infty),\qquad F_Y(y)=F(+\infty,y)$$

**连续型**情形：
$$f_X(x)=\int_{-\infty}^{+\infty}f(x,y)\,dy,\qquad f_Y(y)=\int_{-\infty}^{+\infty}f(x,y)\,dx$$
即**边缘密度 = 联合密度对另一个变量积分**（几何意义：沿一个方向"投影"）。

## 条件分布与独立性

$f_{X\mid Y}(x\mid y)=\dfrac{f(x,y)}{f_Y(y)}$（当 $f_Y(y)>0$）。

$X$ 与 $Y$ **相互独立** $\iff F(x,y)=F_X(x)F_Y(y)\iff f(x,y)=f_X(x)f_Y(y)$。

## 协方差与相关系数

$$\mathrm{Cov}(X,Y)=E[(X-E[X])(Y-E[Y])]=E[XY]-E[X]E[Y]$$
$$\rho_{XY}=\frac{\mathrm{Cov}(X,Y)}{\sqrt{\mathrm{Var}(X)\mathrm{Var}(Y)}},\qquad |\rho_{XY}|\le 1$$

性质：$\mathrm{Var}(X\pm Y)=\mathrm{Var}(X)+\mathrm{Var}(Y)\pm 2\mathrm{Cov}(X,Y)$。

注意：**不相关（$\rho=0$）与独立不等价**；但对二维正态分布二者等价。

# ch04 数字特征

## 数学期望

离散：$E[X]=\sum_k x_k p_k$；连续：$E[X]=\int_{-\infty}^{+\infty}x f(x)\,dx$。

性质：$E[aX+b]=aE[X]+b$；$E[X+Y]=E[X]+E[Y]$（无需独立）；
若 $X,Y$ 独立则 $E[XY]=E[X]E[Y]$。

## 方差

$$\mathrm{Var}(X)=E[(X-E[X])^2]=E[X^2]-(E[X])^2$$
性质：$\mathrm{Var}(aX+b)=a^2\mathrm{Var}(X)$。
**切比雪夫不等式**：$P(|X-E[X]|\ge \varepsilon)\le \dfrac{\mathrm{Var}(X)}{\varepsilon^2}$。

## 矩与矩母函数

$k$ 阶原点矩 $E[X^k]$，$k$ 阶中心矩 $E[(X-E[X])^k]$。
**矩母函数** $M_X(t)=E[e^{tX}]$，满足 $E[X^n]=M_X^{(n)}(0)$。
独立随机变量之和的矩母函数等于各自矩母函数之积。

# ch05 大数定律与中心极限定理

## 大数定律

**辛钦大数定律**：设 $X_i$ 独立同分布且 $E[X_i]=\mu$ 存在，则
$$\frac{1}{n}\sum_{i=1}^{n}X_i \xrightarrow{P} \mu$$
即样本均值依概率收敛于总体均值 —— 这是"用频率估计概率"的理论依据。

## 中心极限定理

**林德伯格–列维定理**：设 $X_i$ 独立同分布，$E[X_i]=\mu$，$\mathrm{Var}(X_i)=\sigma^2>0$，则
$$\frac{\sum_{i=1}^{n}X_i-n\mu}{\sqrt{n}\,\sigma}\xrightarrow{d}N(0,1)$$
等价地，当 $n$ 充分大时 $\bar X \overset{\text{近似}}{\sim} N\!\left(\mu,\dfrac{\sigma^2}{n}\right)$。

**棣莫弗–拉普拉斯定理**：二项分布的正态近似（$np\ge 5$ 且 $n(1-p)\ge 5$ 时效果好）。

CLT 解释了为什么"样本均值的分布会趋近正态" —— 与初始分布的形状无关。

# ch06 统计量及其分布

- 样本均值 $\bar X=\frac{1}{n}\sum X_i$，样本方差 $S^2=\frac{1}{n-1}\sum(X_i-\bar X)^2$。
- $\chi^2$ 分布、$t$ 分布、$F$ 分布由正态总体抽样导出。
- **抽样分布定理**：正态总体下 $\dfrac{(n-1)S^2}{\sigma^2}\sim\chi^2(n-1)$，$\dfrac{\bar X-\mu}{S/\sqrt n}\sim t(n-1)$。

# ch07 参数估计

- **矩估计**：用样本矩代替总体矩解方程。
- **极大似然估计（MLE）**：最大化 $L(\theta)=\prod_i f(x_i;\theta)$，通常解 $\frac{d\ln L}{d\theta}=0$。
- **区间估计**：置信水平 $1-\alpha$，如正态均值区间 $\bar X\pm z_{\alpha/2}\dfrac{\sigma}{\sqrt n}$。
- 评价标准：无偏性、有效性、一致性。

# ch08 假设检验

- 原假设 $H_0$ 与备择假设 $H_1$；两类错误：弃真（$\alpha$）、取伪（$\beta$）。
- 显著性水平 $\alpha$，拒绝域由检验统计量的分位点确定。
- 常见检验：$Z$ 检验、$t$ 检验、$\chi^2$ 拟合优度检验、$F$ 检验。

# ch09 方差分析与回归

- **单因素方差分析**：SST = SSA + SSE，用 $F=\dfrac{SSA/(k-1)}{SSE/(n-k)}$ 检验均值是否全等。
- **一元线性回归**：$\hat\beta_1=\dfrac{\sum(x_i-\bar x)(y_i-\bar y)}{\sum(x_i-\bar x)^2}$，$\hat\beta_0=\bar y-\hat\beta_1\bar x$（最小二乘）。
