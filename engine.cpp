#include <iostream>
#include <vector>
#include <algorithm>

using namespace std;

typedef vector<vector<float>> Matrix;
typedef vector<float> Vector;

float relu(float x) { return max(0.0f, x); }

// V1.2 Cache 局部性优化的核心算子
Matrix linearForward(const Matrix& X, const Matrix& W, const Vector& b) {
    int batchSize = X.size();
    int inputDim = X[0].size();
    int outputDim = W[0].size();
    Matrix Y(batchSize, vector<float>(outputDim, 0.0f));

    for (int i = 0; i < batchSize; ++i) {
        for (int k = 0; k < inputDim; ++k) {
            float x_ik = X[i][k];
            for (int j = 0; j < outputDim; ++j) {
                Y[i][j] += x_ik * W[k][j];
            }
        }
    }
    for (int i = 0; i < batchSize; ++i) {
        for (int j = 0; j < outputDim; ++j) {
            Y[i][j] = relu(Y[i][j] + b[j]);
        }
    }
    return Y;
}

int main() {
    // 1. 张开嘴巴：从标准输入流(stdin)读取外部传入的 3 个特征值
    Matrix X(1, vector<float>(3, 0.0f));
    if (!(cin >> X[0][0] >> X[0][1] >> X[0][2])) {
        cout << "{\"error\": \"数据传输中断或格式错误\"}" << endl;
        return 1;
    }

    // 2. 固化在引擎里的神经网络权重 (Mock 训练好的模型)
    Matrix W = {{0.1, -0.2}, {-0.3, 0.4}, {0.5, -0.6}};
    Vector b = {0.1, 0.5};

    // 3. 核心计算
    Matrix Y = linearForward(X, W, b);

    // 4. 吐出纯净的 JSON 结果
    cout << "{\"status\": \"success\", \"prediction\": [" << Y[0][0] << ", " << Y[0][1] << "]}" << endl;
    return 0;
}
