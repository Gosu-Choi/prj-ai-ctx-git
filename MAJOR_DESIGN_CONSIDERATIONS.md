# ctxgit 주요 설계 고려사항

이 문서는 ctxgit을 확장할 때 잊으면 안 되는 핵심 불변조건을 기록한다.
구현 편의보다 이 문서의 데이터 의미와 사용자 모델을 우선한다.

## 1. Git 커밋 해시는 영구 식별자가 아니다

ctxgit 내부 Git의 commit hash는 현재 스냅샷을 가리키는 구현 세부사항이다.
메시지, 턴, 브랜치, 작업의 영구 ID로 사용하지 않는다.

- 메시지의 논리적 식별자는 history record의 `id`다.
- 턴의 논리적 식별자는 `turnId`다.
- 브랜치의 논리적 식별자는 branch `id`다.
- commit hash는 특정 시점의 tree를 읽거나 진단할 때만 사용한다.
- API, URL, 외부 연동, 사용자 북마크, 데이터베이스 키에 commit hash를
  안정적인 ID처럼 노출하거나 저장하지 않는다.
- commit hash를 저장해야 한다면 언제든 다시 계산하거나 교체할 수 있는
  파생값 또는 캐시로 취급한다.

메시지 수정으로 history rewrite가 수행되면 수정 지점 이후의 commit
hash는 모두 바뀔 수 있다. 브랜치 이름과 논리적 ID는 그대로 유지한다.

## 2. 메시지 수정의 의미

기본 `Revise message`는 해당 브랜치의 역사를 수정하는 작업이다.
수정 지점 이후의 내부 Git commit chain을 재작성할 수 있다.

단, 다음 작업은 기본 수정에 포함하지 않는다.

- 이후 AI 응답 재생성
- 이후 `context.md` 재작성
- 이후 artifacts 또는 notes 재생성
- 다른 브랜치에 이미 복제된 역사의 자동 수정

수정된 메시지에서 새로운 AI 진행을 만들고 싶다면 기존 `Fork` 흐름을
사용한다. 향후 별도 기능을 추가하더라도 단순 수정과 AI 재생성을 같은
작업으로 암묵적으로 묶지 않는다.

## 3. History rewrite 구현 규칙

내부 Git 역사를 재작성할 때는 다음 대상을 하나의 원자적 작업처럼
갱신해야 한다.

- 수정 지점 이후의 commit chain
- `refs/ctxgit/branches/<branch-id>`
- 영향을 받는 `refs/ctxgit/turns/<turn-id>`
- 내부 Git `HEAD`
- commit hash를 담은 파생 메타데이터

재작성 도중 실패하면 기존 브랜치 ref가 그대로 유효해야 한다. 새 chain을
전부 만든 후 마지막에 ref를 교체한다.

현재 제품 정책은 수정 전 history 복구를 제공하지 않는다. 별도의 복구용
ref를 만들지 않으며, rewrite 완료 후 이전 commit chain은 도달 불가능해질
수 있다.

## 4. 현재 commit hash 의존 지점

현재 코드에는 다음과 같은 hash 의존이 존재한다. history rewrite를
구현할 때 반드시 함께 검토한다.

- `refs/ctxgit/turns/<turnId>`가 스냅샷 commit을 가리킨다.
- `refs/ctxgit/branches/<branchId>`가 브랜치 HEAD를 가리킨다.
- Fork/Cut은 turn ref로 과거 파일 스냅샷을 찾는다.
- API의 `turnCommit.commit`, Git 상태 화면, 테스트가 commit hash를
  진단 정보로 사용한다.
- merge commit은 source branch commit들을 parent로 가질 수 있다.

이 중 commit hash 자체를 논리적 ID로 간주하는 기능은 만들지 않는다.
원본 브랜치가 이후 재작성되어도 기존 fork의 의미는 바뀌지 않는다.

## 5. Fork와 Cut의 의미

- Fork는 선택 시점의 파일 상태를 복원하되, 선택 범위의 현재 history
  revision을 사용한다.
- 이미 생성된 fork는 원본 브랜치의 이후 revise/rewrite를 자동으로
  따라가지 않는 독립된 브랜치다.
- Cut은 선택 시점 이후를 제거하지만, 선택 시점 이전 메시지의 최신
  revision을 보존해야 한다.
- 메시지 하나가 여러 record로 구성된 turn의 중간이라면 Cut을 허용하지
  않는다.

History rewrite가 도입된 뒤에도 이 사용자 의미는 유지되어야 한다.

## 6. 파생 데이터의 정합성

다음 데이터는 history에서 파생되거나 history의 영향을 받을 수 있다.

- compactions
- `context.md`
- artifacts
- research notes
- merge summaries와 archived source snapshots

메시지를 수정하면 compactions처럼 직접적인 history 요약은 무효화해야
한다. 반면 `context.md`, artifacts, notes는 자동 재생성하지 않는다.
필요하면 향후 provenance와 stale 상태를 표시하되, 사용자가 작성하거나
AI가 생성한 파일을 암묵적으로 삭제하지 않는다.

## 7. 향후 기능 개발 시 금지 사항

- commit hash를 변경 불가능한 공개 ID로 가정하지 않는다.
- branch ref를 먼저 이동한 뒤 rewrite 작업을 시작하지 않는다.
- 원본 브랜치 rewrite를 기존 fork에 암묵적으로 전파하지 않는다.
- 메시지 수정만으로 AI 호출이나 파일 재생성을 자동 실행하지 않는다.
- `history.jsonl`만 수정하고 관련 turn/branch refs를 불일치 상태로 두지
  않는다.

## 8. 구현 전 확인 목록

내부 Git이나 history를 변경하는 기능을 추가하기 전에 확인한다.

1. 논리적 ID와 commit hash를 구분했는가?
2. rewrite 후 모든 branch/turn ref가 올바른 새 commit을 가리키는가?
3. 기존 fork와 merge의 의미가 유지되는가?
4. 실패 시 기존 history로 원자적으로 복구 가능한가?
5. compaction 등 직접 파생 데이터를 무효화했는가?
6. AI 재생성을 사용자의 명시적 요청 없이 실행하지 않는가?
