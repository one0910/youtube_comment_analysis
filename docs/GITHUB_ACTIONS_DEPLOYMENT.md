# GitHub Actions 自動部署 TubeSense

這台 EC2 同時運行 Water Drop。TubeSense 使用主機 Port 8090，Water Drop Gateway 持有 Port 80 並轉送至 8090。本流程在 GitHub CI 成功後，由 GitHub OIDC 取得短效 AWS 憑證，透過 SSM 請 EC2 自行更新原始碼和 Docker Compose。Docker Image 在 EC2 建置，不推送 ECR。

## 目前 AWS 設定

- AWS 帳號：`236451047930`，區域：`ap-southeast-1`
- EC2：`i-02ae0f67421f91786`
- EC2 已附加 `TubeSenseEC2SSMRole`，Fleet Manager 顯示 Online。
- OIDC Provider：`arn:aws:iam::236451047930:oidc-provider/token.actions.githubusercontent.com`，Audience：`sts.amazonaws.com`

## 1. 建立 GitHub 專用 IAM Role

在 IAM 建立 `TubeSenseGitHubDeployRole`，信任政策設定為：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::236451047930:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:one0910@39715455/youtube_comment_analysis@1345044843:environment:production"
        }
      }
    }
  ]
}
```

此 repository 建立於 2026 年 8 月，因此 OIDC subject 包含 GitHub owner ID 和 repository ID。Role 的內嵌權限政策：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SendCommandOnlyToTubeSenseEC2",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:ap-southeast-1:236451047930:instance/i-02ae0f67421f91786",
        "arn:aws:ssm:ap-southeast-1::document/AWS-RunShellScript"
      ]
    },
    {
      "Sid": "ReadCommandResult",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

`AWS-RunShellScript` 是 AWS 擁有的文件，ARN 的帳號欄位為空（雙冒號 `::`）。之前提供的範例在此欄填入本帳號，請以這份為準。這個權限可以在指定 EC2 執行 Shell，應只給受保護的部署流程使用。

## 2. 設定 GitHub Environment

到 `one0910/youtube_comment_analysis` 的 Settings → Environments，建立名稱完全相同的 `production` Environment。Deployment branches 限制為 `main`。目前流程希望 push 後自動部署，因此不要設定必須人工批准的 reviewers。

此流程不需要在 GitHub 儲存 AWS Access Key、Secret Access Key、SSH 私鑰或正式應用程式金鑰。正式 `.env.production`、`.env.postgres` 繼續留在 EC2。

## 3. 檢查 EC2 主機

在 `/home/ubuntu/tubesense-ai`：

```bash
git status --short
git branch --show-current
grep '^TUBESENSE_HTTP_PORT=' .env.production
docker compose --env-file .env.production -f compose.production.yaml config --quiet
id -nG ubuntu
```

預期 Git 追蹤檔案無未提交修改、分支為 `main`、Port 為 `8090`、`ubuntu` 使用者可執行 Docker。`git pull --ff-only` 若遇到 EC2 上未提交的追蹤檔案變更，會停止部署；先在主機處理這些變更，不要覆蓋。

## 4. 執行方式

將 `.github/workflows/ci.yml`、`.github/workflows/cd(deploy).yml` 和 `scripts/git_update_script.sh` 提交並 push 到 `main` 後：

1. CI 安裝相依套件、編譯 CSS、檢查 Django 設定與 migration，並執行測試；GitHub 不建置 Docker Image。
2. `CI階段` 成功且事件是同一 repository 的 `main` push 時，`CD階段` workflow 使用 OIDC 暫時扮演 `TubeSenseGitHubDeployRole`。
3. SSM 在指定 EC2 執行 `git pull --ff-only origin main`，以該次 CI 通過的 SHA 做比對。若 main 已往前移，較舊執行會略過。
4. 在 EC2 建置 Image，更新 web、worker、nginx；重新啟動 nginx 以刷新 upstream DNS；確認健康狀態。

SSM Run Command 可在 AWS Systems Manager → 執行命令查看。GitHub Actions 的 `CD階段` 頁面也會顯示 SSM Command ID、執行狀態與有限長度的 stdout/stderr。部署失敗時不會執行 `docker compose down` 或刪除 volumes；若失敗發生於服務更新之後，需依 log 檢查並人工處理。

此主機只有約 1 GiB 記憶體，Image 建置時應留意 `free -h`、swap 和 Docker 日誌。未來若建置造成主機壓力，可改成 GitHub 建置 Image 並推送 ECR；OIDC 與 SSM 的身分和遠端命令設計仍可沿用。
