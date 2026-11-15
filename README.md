# Ten thousand monkeys

`10km` is a lightweight and flexible agent loop.

The Ralph loop iterates over a plan, the Karpathy loop optimises to a goal. The Monkey loop can do either, or both: it is a generalized loop, which you can be in, on, or outside.

In 10km, monkey agents act in four roles:
- Planner: Refines the plan into tasks
- Workers: Perform tasks
- Curator: Validates worker output
- Auditor: Inspects and improves the loop

The work is done in cycles, with a session per agent. You can run your own sessions in parallel, with an agent or without. The Curator merges it into the project.

You kick off a Monkey loop with your goals, deliverables and a high-level plan. If you're short on these, don't worry: just tell the loop what you want it to do. You can always change it later. The loop will continue running until its done, or until you tell it otherwise.

10km is designed to run in a sandbox, and to work well with small models. The loop can use any harness, with local or remote models. You can interfere with the monkeys at any time, or run your own parallel sessions.

The monkeys may use and abuse any tools you give them access to. It would be a mistake to let them out of their sandbox.


Jorge Luis Borges explored the Infinite Monkey Theorem in his 1939 essay "The Total Library" (La biblioteca total). Borges referenced the idea—often attributed to Thomas Huxley—that "a half-dozen monkeys provided with typewriters would, in a few eternities, produce all the books in the British Museum".
"Strictly speaking, one immortal monkey would suffice".
 Two years later, in 1941, Borges transformed this probabilistic thought experiment into his famous short story "The Library of Babel". Borges imagined a universe consisting of endless hexagonal galleries containing books with every possible permutation of 25 basic symbols. Like the output of random typing, the library holds every masterpiece, the true history of the future, and the exact account of your death. However, these meaningful texts are buried inside an ocean of incomprehensible nonsense.
 
