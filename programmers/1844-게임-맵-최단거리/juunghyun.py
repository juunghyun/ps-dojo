from collections import deque

def solution(maps):
    n, m = len(maps), len(maps[0])
    visited = [[0] * m for _ in range(n)]   # 초기화하면서 이차원 리스트 만들기
    direction = [(-1,0), (1,0), (0,-1), (0,1)]

    q = deque()
    q.append((0, 0))            # 시작 지점 넣기
    visited[0][0] = 1

    while q:
        cy, cx = q.popleft()
        for dy, dx in direction:
            ny, nx = cy + dy, cx + dx

            # 맵 안에있고 벽 아니고 방문한적 없으면
            if 0 <= ny < n and 0 <= nx < m and maps[ny][nx] != 0 and visited[ny][nx] == 0:
                visited[ny][nx] = visited[cy][cx] + 1   # 거리 표기
                if (ny, nx) == (n-1, m-1):
                    return visited[ny][nx]
                q.append((ny, nx))

    return -1