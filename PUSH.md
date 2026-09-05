# Push M1 into MQDIGITALRADIO/MQ

This tree was built locally (no clone). Zip: `MQ-Radio-Automation-M1.zip`.

## Option A — empty / new remote contents

```bash
# unzip wherever you like
unzip MQ-Radio-Automation-M1.zip -d mq-radio-automation
cd mq-radio-automation

git init
git add .
git commit -m "M1: MQ Radio Automation — Living Log scheduler, MockEngine, On-Air prototype"

# create remote if needed, then:
git branch -M main
git remote add origin https://github.com/MQDIGITALRADIO/MQ.git
git push -u origin main
```

If the GitHub repo already has commits (e.g. README), use Option B.

## Option B — merge into existing MQ repo

```bash
git clone https://github.com/MQDIGITALRADIO/MQ.git
cd MQ

# copy M1 files on top (adjust path to your unzip location)
cp -a /path/to/mq-radio-automation/. .

git add .
git commit -m "M1: MQ Radio Automation — Living Log scheduler, MockEngine, On-Air prototype"
git push origin HEAD
```

## Option C — orphan branch then PR

```bash
git clone https://github.com/MQDIGITALRADIO/MQ.git
cd MQ
git checkout --orphan m1-radio-automation
git rm -rf . 2>/dev/null || true
cp -a /path/to/mq-radio-automation/. .
git add .
git commit -m "M1: MQ Radio Automation"
git push -u origin m1-radio-automation
# open PR on GitHub: m1-radio-automation → main
```

Auth: use `gh auth login` or a personal access token / SSH remote as you normally do.
