---- MODULE EssentialPaxos ----
EXTENDS Naturals, FiniteSets, TLC

(*
  Networking-agnostic single-decree Paxos:
  Proposers, Acceptors, Learners with an asynchronous message bag `msgs`.
*)

CONSTANTS
  Acceptors,
  Proposers,
  Learners,
  Values,
  NoValue,
  MaxBallot

(*
  Proposal ids and ordering helpers
*)
NoProposal == <<0, 0>>
ProposalIDs == (1..MaxBallot) \X Proposers
ProposalIDOrNone == ProposalIDs \cup {NoProposal}

ProposalNum(pid) == pid[1]
ProposalOwnerRank(pid) == pid[2]
ProposalIDLt(a, b) ==
  ProposalNum(a) < ProposalNum(b)
  \/ (ProposalNum(a) = ProposalNum(b) /\ ProposalOwnerRank(a) < ProposalOwnerRank(b))
ProposalIDLeq(a, b) == a = b \/ ProposalIDLt(a, b)
ProposalIDGeq(a, b) == ProposalIDLeq(b, a)

(*
  Majority
*)
QuorumSize == (Cardinality(Acceptors) \div 2) + 1
Majority(S) == Cardinality(S) * 2 > Cardinality(Acceptors)

(*
  Message shapes
*)
PrepareMsg(p, a, pid) ==
  [kind |-> "Prepare", from |-> p, to |-> a, pid |-> pid]

PromiseMsg(a, p, pid, prevId, prevVal) ==
  [kind |-> "Promise", from |-> a, to |-> p, pid |-> pid, prevId |-> prevId, prevVal |-> prevVal]

AcceptMsg(p, a, pid, v) ==
  [kind |-> "Accept", from |-> p, to |-> a, pid |-> pid, val |-> v]

AcceptedMsg(a, l, pid, v) ==
  [kind |-> "Accepted", from |-> a, to |-> l, pid |-> pid, val |-> v]

Messages ==
  { PrepareMsg(p, a, pid) : p \in Proposers, a \in Acceptors, pid \in ProposalIDs } \cup
  { PromiseMsg(a, p, pid, prevId, prevVal) :
      a \in Acceptors, p \in Proposers, pid \in ProposalIDs,
      prevId \in ProposalIDOrNone,
      prevVal \in (Values \cup {NoValue}) } \cup
  { AcceptMsg(p, a, pid, v) : p \in Proposers, a \in Acceptors, pid \in ProposalIDs, v \in Values } \cup
  { AcceptedMsg(a, l, pid, v) : a \in Acceptors, l \in Learners, pid \in ProposalIDs, v \in Values }

(*
  State variables
*)
VARIABLES
  msgs,                 \* set of in-flight messages
  \* Proposers' state
  proposalId,           \* [Proposers -> ProposalIDOrNone]
  nextPropNum,          \* [Proposers -> 1..(MaxBallot+1)]
  promisesRcvd,         \* [Proposers -> SUBSET Acceptors]
  lastAcceptedId,       \* [Proposers -> ProposalIDOrNone]
  proposedVal,          \* [Proposers -> Values \cup {NoValue}]
  \* Acceptors' state
  promisedId,           \* [Acceptors -> ProposalIDOrNone]
  acceptedId,           \* [Acceptors -> ProposalIDOrNone]
  acceptedVal,          \* [Acceptors -> Values \cup {NoValue}]
  \* Learners' state
  latestFromAcc,        \* [Learners -> [Acceptors -> ProposalIDOrNone]]
  valueForPid,          \* [Learners -> [ProposalIDs -> Values \cup {NoValue}]]
  finalPid,             \* [Learners -> ProposalIDOrNone]
  finalValue            \* [Learners -> Values \cup {NoValue}]

vars ==
  << msgs, proposalId, nextPropNum, promisesRcvd, lastAcceptedId, proposedVal,
     promisedId, acceptedId, acceptedVal,
     latestFromAcc, valueForPid, finalPid, finalValue >>

(*
  Type correctness
*)
TypeOK ==
  /\ msgs \subseteq Messages
  /\ proposalId \in [Proposers -> ProposalIDOrNone]
  /\ nextPropNum \in [Proposers -> 1..(MaxBallot+1)]
  /\ promisesRcvd \in [Proposers -> SUBSET Acceptors]
  /\ lastAcceptedId \in [Proposers -> ProposalIDOrNone]
  /\ proposedVal \in [Proposers -> Values \cup {NoValue}]
  /\ promisedId \in [Acceptors -> ProposalIDOrNone]
  /\ acceptedId \in [Acceptors -> ProposalIDOrNone]
  /\ acceptedVal \in [Acceptors -> Values \cup {NoValue}]
  /\ latestFromAcc \in [Learners -> [Acceptors -> ProposalIDOrNone]]
  /\ valueForPid \in [Learners -> [ProposalIDs -> Values \cup {NoValue}]]
  /\ finalPid \in [Learners -> ProposalIDOrNone]
  /\ finalValue \in [Learners -> Values \cup {NoValue}]

(*
  Initial state
*)
Init ==
  /\ msgs = {}
  /\ proposalId = [p \in Proposers |-> NoProposal]
  /\ nextPropNum = [p \in Proposers |-> 1]
  /\ promisesRcvd = [p \in Proposers |-> {}]
  /\ lastAcceptedId = [p \in Proposers |-> NoProposal]
  /\ proposedVal = [p \in Proposers |-> NoValue]
  /\ promisedId = [a \in Acceptors |-> NoProposal]
  /\ acceptedId = [a \in Acceptors |-> NoProposal]
  /\ acceptedVal = [a \in Acceptors |-> NoValue]
  /\ latestFromAcc = [l \in Learners |-> [a \in Acceptors |-> NoProposal]]
  /\ valueForPid = [l \in Learners |-> [pid \in ProposalIDs |-> NoValue]]
  /\ finalPid = [l \in Learners |-> NoProposal]
  /\ finalValue = [l \in Learners |-> NoValue]

(*
  1. Prepare: proposer starts Phase 1
*)
Prepare(p) ==
  /\ p \in Proposers
  /\ nextPropNum[p] \in 1..MaxBallot
  /\ LET pidNew == << nextPropNum[p], p >> IN
       /\ proposalId' = [proposalId EXCEPT ![p] = pidNew]
       /\ nextPropNum' = [nextPropNum EXCEPT ![p] = @ + 1]
       /\ promisesRcvd' = [promisesRcvd EXCEPT ![p] = {}]
       /\ msgs' = msgs \cup { PrepareMsg(p, a, pidNew) : a \in Acceptors }
       /\ UNCHANGED << lastAcceptedId, proposedVal,
                      promisedId, acceptedId, acceptedVal,
                      latestFromAcc, valueForPid, finalPid, finalValue >>

(*
  2. HandlePrepare: acceptor processes a Prepare
*)
HandlePrepare(a, m) ==
  /\ a \in Acceptors
  /\ m \in msgs
  /\ m.kind = "Prepare"
  /\ m.to = a
  /\ ProposalIDGeq(m.pid, promisedId[a])
  /\ LET doUpdate == ProposalIDLt(promisedId[a], m.pid) IN
       /\ promisedId' = [promisedId EXCEPT ![a] = IF doUpdate THEN m.pid ELSE @]
       /\ msgs' = msgs \cup { PromiseMsg(a, m.from, m.pid, acceptedId[a], acceptedVal[a]) }
       /\ UNCHANGED << proposalId, nextPropNum, promisesRcvd, lastAcceptedId, proposedVal,
                      acceptedId, acceptedVal,
                      latestFromAcc, valueForPid, finalPid, finalValue >>

(*
  3. HandlePromise: proposer processes a Promise
*)
HandlePromise(p, m) ==
  /\ p \in Proposers
  /\ m \in msgs
  /\ m.kind = "Promise"
  /\ m.to = p
  /\ m.pid = proposalId[p]
  /\ ~(m.from \in promisesRcvd[p])
  /\ LET greater == ProposalIDLt(lastAcceptedId[p], m.prevId) IN
     LET newPropVal == IF greater /\ m.prevVal # NoValue THEN m.prevVal ELSE proposedVal[p] IN
     LET newSet == promisesRcvd[p] \cup { m.from } IN
     LET sendAcc == (Cardinality(newSet) = QuorumSize) /\ newPropVal # NoValue IN
     LET accMsgs == IF sendAcc
                    THEN { AcceptMsg(p, a, proposalId[p], newPropVal) : a \in Acceptors }
                    ELSE {} IN
       /\ promisesRcvd' = [promisesRcvd EXCEPT ![p] = newSet]
       /\ lastAcceptedId' = [lastAcceptedId EXCEPT ![p] = IF greater THEN m.prevId ELSE @]
       /\ proposedVal' = [proposedVal EXCEPT ![p] = newPropVal]
       /\ msgs' = msgs \cup accMsgs
       /\ UNCHANGED << proposalId, nextPropNum,
                      promisedId, acceptedId, acceptedVal,
                      latestFromAcc, valueForPid, finalPid, finalValue >>

(*
  4. HandleAccept: acceptor processes an Accept request
*)
HandleAccept(a, m) ==
  /\ a \in Acceptors
  /\ m \in msgs
  /\ m.kind = "Accept"
  /\ m.to = a
  /\ ProposalIDGeq(m.pid, promisedId[a])
  /\ promisedId' = [promisedId EXCEPT ![a] = m.pid]
  /\ acceptedId' = [acceptedId EXCEPT ![a] = m.pid]
  /\ acceptedVal' = [acceptedVal EXCEPT ![a] = m.val]
  /\ msgs' = msgs \cup { AcceptedMsg(a, l, m.pid, m.val) : l \in Learners }
  /\ UNCHANGED << proposalId, nextPropNum, promisesRcvd, lastAcceptedId, proposedVal,
                 latestFromAcc, valueForPid, finalPid, finalValue >>

(*
  5. HandleAccepted: learner processes an Accepted notification
*)
HandleAccepted(l, m) ==
  /\ l \in Learners
  /\ m \in msgs
  /\ m.kind = "Accepted"
  /\ m.to = l
  /\ finalValue[l] = NoValue
  /\ ProposalIDLt(latestFromAcc[l][m.from], m.pid)
  /\ valueForPid[l][m.pid] = NoValue \/ valueForPid[l][m.pid] = m.val
  /\ LET lfaNew == [latestFromAcc EXCEPT ![l][m.from] = m.pid] IN
     LET vfpNew == [valueForPid EXCEPT ![l][m.pid] =
                       IF valueForPid[l][m.pid] = NoValue THEN m.val ELSE @] IN
     LET agreeing == { a2 \in Acceptors : lfaNew[l][a2] = m.pid } IN
       /\ latestFromAcc' = lfaNew
       /\ valueForPid' = vfpNew
       /\ finalPid' = [finalPid EXCEPT ![l] = IF Majority(agreeing) THEN m.pid ELSE @]
       /\ finalValue' = [finalValue EXCEPT ![l] = IF Majority(agreeing) THEN m.val ELSE @]
       /\ UNCHANGED << msgs,
                      proposalId, nextPropNum, promisesRcvd, lastAcceptedId, proposedVal,
                      promisedId, acceptedId, acceptedVal >>

(*
  Optional external input: set a proposer's initial proposal value (once)
*)
SetProposal(p, v) ==
  /\ p \in Proposers
  /\ v \in Values
  /\ proposedVal[p] = NoValue
  /\ proposedVal' = [proposedVal EXCEPT ![p] = v]
  /\ UNCHANGED << msgs, proposalId, nextPropNum, promisesRcvd, lastAcceptedId,
                 promisedId, acceptedId, acceptedVal,
                 latestFromAcc, valueForPid, finalPid, finalValue >>

Next ==
  \/ (\E p \in Proposers : Prepare(p))
  \/ (\E a \in Acceptors, m \in msgs : HandlePrepare(a, m))
  \/ (\E p \in Proposers, m \in msgs : HandlePromise(p, m))
  \/ (\E a \in Acceptors, m \in msgs : HandleAccept(a, m))
  \/ (\E l \in Learners, m \in msgs : HandleAccepted(l, m))
  \/ (\E p \in Proposers, v \in Values : SetProposal(p, v))

Spec == Init /\ [][Next]_vars

====