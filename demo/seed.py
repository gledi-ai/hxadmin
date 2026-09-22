from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from demo.models import Project, Task, TaskStatus, User


async def seed(session: AsyncSession) -> None:
    if await session.scalar(select(User.id).limit(1)) is not None:
        return
    ada = User(name="Ada Lovelace", email="ada@example.com")
    linus = User(name="Linus Torvalds", email="linus@example.com")
    grace = User(name="Grace Hopper", email="grace@example.com")
    website = Project(name="Website", description="Marketing site", members=[ada, grace])
    kernel = Project(name="Kernel", description="Core engine", members=[linus, ada])
    session.add_all(
        [
            Task(
                title="Design homepage", project=website, assignee=ada, due_date=date(2026, 10, 1)
            ),
            Task(title="Write copy", project=website, assignee=grace, status=TaskStatus.doing),
            Task(title="Set up analytics", project=website, priority=5),
            Task(
                title="Fix scheduler bug",
                project=kernel,
                assignee=linus,
                status=TaskStatus.done,
                priority=1,
            ),
            Task(title="Add async IO", project=kernel, assignee=ada, due_date=date(2026, 11, 15)),
            Task(title="Benchmark release", project=kernel, status=TaskStatus.todo),
        ]
    )
    await session.commit()
