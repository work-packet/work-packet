# Agents and Persistence
Currently, lifetime and persistence are 
- Team of ephemeral agents working on shared data
- That database is the center
  - Must check hierarchical nature, ability to send messages, etc

- Want agents to store relevant data in files instead of context
- Have lightweight OS for working with this shared data

- Process
  - identity: directory with symlinks to external resources, such as dependencies (ivpm), cache (dv-flow)
  - local state -- selectively cloned from parent
  - next instruction
    - must return next instruction as part of status
  - stack
  - 

- Long-term