
This project started as an agent-management system. I think it
may be more of a new way of working.

Work packets become our new containerization unit for tech work.
The work packet server must be multi-user and allow users to 
pass work between. Each work packet will, effectively, have a
unique URL by which it's tracked. 

Work packets may be created in various different ways. For example,
when a test fails, I might create a work packet containing the 
transcript and waves.

I might decide to create a new project within the dashboard. 

Work packets need some sort of setup information. For example, we
might only want to store the reference to the design with a failing
test in the packet -- allowing for the proper revision to be 
cloned. 

Work packets likely also need a tear-down / clean-up step to allow
derived data to be expunged. We'll often do before hand-off (and, it's likely the default).

We'll have to think carefully about where packets may live, since
we want maximum flexibility. For example, if a test in github CI 
fails, I might create a work packet as an artifact. I might have 
an R2 bucket or S3 bucket where work packets get stored. Either way,
we'll need the ability to initialize the local clone of a remote
packet.

The web dashboard is the portal to work packets on my board. For
real work, though, I typically want to drop into an IDE. Here, we'll
need to let the user choose the view -- full packet, work folder,
repo within the work folder, etc. Is should be able to either 
drop directly into VSCode web or launch the standalone app. Should 
we consider the OSS version too?

Currently, we do a good job of displaying run status of agent jobs
via the todo list. We'll also want a way for long-running non-agentic
jobs to report status. Things like dv-flow-mgr, for example. We 
should be able to start a dv-flow-mgr run in a work packet and
see progress in the dashboard -- bonus points if we can show the
graph and what portions have been covered. We may have other tools
from which we can get status info.

Some of this raises a question of associating an active session 
with a work packet. Having an idle shell session open is lightweight.
I wonder if we can detect the difference between an idle and an
active session in the dash server. If so, the dash server can
reap and restore idle sessions, while retaining active ones. 
-> We might be able to worry about this later. The overall goal
is to ensure that users can think of packets as resumable and 
as mini-containers where active work can be ongoing. Likely 
the recommendation is to use job-submission tools (SLURM) for
heavy-weight jobs

The dashboard will need templates for creating work packets. We might
have core tasks that we can carry out with a few inputs from the user.
We might have 'create from X' -- create from github repo/ref, 
create (agentically) from github issue, etc.

We'll need some sort of persistent server / scheduler. This should
be aware of resources (number of active sessions requiring X resource 
  (eg agent session), etc). We might need a pluggable way to 
running batch (agent, single-command) sessions. For example, launching
via SLURM. 


