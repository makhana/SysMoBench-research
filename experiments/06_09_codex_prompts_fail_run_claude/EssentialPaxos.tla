---- MODULE EssentialPaxos ----
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Acceptors, Proposers, Learners, Values, NoValue, MaxBallot

NoProposal == <<0, 0>>

ProposalIDs == (1..MaxBallot) \X Proposers
ProposalIDOrNone == ProposalIDs \cup {NoProposal}

ProposalNum(pid) == pid[1]
ProposalOwnerRank(pid) == pid[2]
ProposalIDLt(a, b) == ProposalNum(a) < ProposalNum(b) \/ (ProposalNum(a) = ProposalNum(b) /\ ProposalOwnerRank(a) < ProposalOwnerRank(b))
ProposalIDLeq(a, b) == a = b \/ ProposalIDLt(a, b)
ProposalIDGeq(a, b) == ProposalIDLeq(b, a)

Majority(S) == Cardinality(S) * 2 > Cardinality(Acceptors)

NextProposalNum(p) == IF proposalId[p] = NoProposal THEN 1 ELSE ProposalNum(proposalId[p]) + 1

VARIABLES
    msgs,
    proposalId,
    proposedVal,
    promisesRcvd,
    lastAcceptedId,
    promisedId,
    acceptedId,
    acceptedVal,
    finalPid,
    finalValue

vars == <<msgs, proposalId, proposedVal, promisesRcvd, lastAcceptedId, promisedId, acceptedId, acceptedVal, finalPid, finalValue>>

TypeOK ==
    /\ msgs \subseteq [kind: {"Prepare", "Promise", "Accept", "Accepted"}, from: Proposers \cup Acceptors, to: Proposers \cup Acceptors \cup Learners, pid: ProposalIDOrNone, prevPid: ProposalIDOrNone, val: Values \cup {NoValue}]
    /\ proposalId \in [Proposers -> ProposalIDOrNone]
    /\ proposedVal \in [Proposers -> Values \cup {NoValue}]
    /\ promisesRcvd \in [Proposers -> SUBSET Acceptors]
    /\ lastAcceptedId \in [Proposers -> ProposalIDOrNone]
    /\ promisedId \in [Acceptors -> ProposalIDOrNone]
    /\ acceptedId \in [Acceptors -> ProposalIDOrNone]
    /\ acceptedVal \in [Acceptors -> Values \cup {NoValue}]
    /\ finalPid \in [Learners -> ProposalIDOrNone]
    /\ finalValue \in [Learners -> Values \cup {NoValue}]

Init ==
    /\ msgs = {}
    /\ proposalId = [p \in Proposers |-> NoProposal]
    /\ proposedVal = [p \in Proposers |-> NoValue]
    /\ promisesRcvd = [p \in Proposers |-> {}]
    /\ lastAcceptedId = [p \in Proposers |-> NoProposal]
    /\ promisedId = [a \in Acceptors |-> NoProposal]
    /\ acceptedId = [a \in Acceptors |-> NoProposal]
    /\ acceptedVal = [a \in Acceptors |-> NoValue]
    /\ finalPid = [l \in Learners |-> NoProposal]
    /\ finalValue = [l \in Learners |-> NoValue]

Prepare(p) ==
    /\ \/ /\ proposedVal[p] = NoValue
          /\ \E v \in Values:
             /\ proposedVal' = [proposedVal EXCEPT ![p] = v]
             /\ promisesRcvd' = [promisesRcvd EXCEPT ![p] = {}]
             /\ proposalId' = [proposalId EXCEPT ![p] = <<NextProposalNum(p), p>>]
             /\ msgs' = msgs \cup {[kind |-> "Prepare", from |-> p, to |-> a, pid |-> <<NextProposalNum(p), p>>, prevPid |-> NoProposal, val |-> NoValue] : a \in Acceptors}
       \/ /\ proposedVal[p] # NoValue
          /\ promisesRcvd' = [promisesRcvd EXCEPT ![p] = {}]
          /\ proposalId' = [proposalId EXCEPT ![p] = <<NextProposalNum(p), p>>]
          /\ msgs' = msgs \cup {[kind |-> "Prepare", from |-> p, to |-> a, pid |-> <<NextProposalNum(p), p>>, prevPid |-> NoProposal, val |-> NoValue] : a \in Acceptors}
          /\ UNCHANGED proposedVal
    /\ UNCHANGED <<lastAcceptedId, promisedId, acceptedId, acceptedVal, finalPid, finalValue>>

HandlePrepare(a, m) ==
    /\ m \in msgs
    /\ m.kind = "Prepare"
    /\ m.to = a
    /\ \/ /\ m.pid = promisedId[a]
          /\ msgs' = msgs \cup {[kind |-> "Promise", from |-> a, to |-> m.from, pid |-> m.pid, prevPid |-> acceptedId[a], val |-> acceptedVal[a]]}
          /\ UNCHANGED promisedId
       \/ /\ ProposalIDLt(promisedId[a], m.pid)
          /\ promisedId' = [promisedId EXCEPT ![a] = m.pid]
          /\ msgs' = msgs \cup {[kind |-> "Promise", from |-> a, to |-> m.from, pid |-> m.pid, prevPid |-> acceptedId[a], val |-> acceptedVal[a]]}
       \/ /\ ProposalIDLt(m.pid, promisedId[a])
          /\ UNCHANGED <<msgs, promisedId>>
    /\ UNCHANGED <<proposalId, proposedVal, promisesRcvd, lastAcceptedId, acceptedId, acceptedVal, finalPid, finalValue>>

HandlePromise(p, m) ==
    /\ m \in msgs
    /\ m.kind = "Promise"
    /\ m.to = p
    /\ m.pid = proposalId[p]
    /\ m.from \notin promisesRcvd[p]
    /\ promisesRcvd' = [promisesRcvd EXCEPT ![p] = promisesRcvd[p] \cup {m.from}]
    /\ LET newLastAcceptedId == IF ProposalIDLt(lastAcceptedId[p], m.prevPid) THEN m.prevPid ELSE lastAcceptedId[p]
           newProposedVal == IF /\ ProposalIDLt(lastAcceptedId[p], m.prevPid) /\ m.val # NoValue
                             THEN m.val
                             ELSE proposedVal[p]
           newPromises == promisesRcvd[p] \cup {m.from}
       IN /\ lastAcceptedId' = [lastAcceptedId EXCEPT ![p] = newLastAcceptedId]
          /\ proposedVal' = [proposedVal EXCEPT ![p] = newProposedVal]
          /\ IF /\ Majority(newPromises)
                /\ newProposedVal # NoValue
             THEN msgs' = msgs \cup {[kind |-> "Accept", from |-> p, to |-> a, pid |-> proposalId[p], prevPid |-> NoProposal, val |-> newProposedVal] : a \in Acceptors}
             ELSE UNCHANGED msgs
    /\ UNCHANGED <<proposalId, promisedId, acceptedId, acceptedVal, finalPid, finalValue>>

HandleAccept(a, m) ==
    /\ m \in msgs
    /\ m.kind = "Accept"
    /\ m.to = a
    /\ ProposalIDGeq(m.pid, promisedId[a])
    /\ promisedId' = [promisedId EXCEPT ![a] = m.pid]
    /\ acceptedId' = [acceptedId EXCEPT ![a] = m.pid]
    /\ acceptedVal' = [acceptedVal EXCEPT ![a] = m.val]
    /\ msgs' = msgs \cup {[kind |-> "Accepted", from |-> a, to |-> l, pid |-> m.pid, prevPid |-> NoProposal, val |-> m.val] : l \in Learners}
    /\ UNCHANGED <<proposalId, proposedVal, promisesRcvd, lastAcceptedId, finalPid, finalValue>>

LatestAcceptedBy(a, l, pid, v) ==
    /\ \E ma \in msgs : ma.kind = "Accepted" /\ ma.from = a /\ ma.to = l /\ ma.pid = pid /\ ma.val = v
    /\ \A mb \in msgs : (mb.kind = "Accepted" /\ mb.from = a /\ mb.to = l) => ProposalIDLeq(mb.pid, pid)

HandleAccepted(l, m) ==
    /\ m \in msgs
    /\ m.kind = "Accepted"
    /\ m.to = l
    /\ IF finalValue[l] # NoValue
       THEN UNCHANGED vars
       ELSE LET agreeing == {a2 \in Acceptors : LatestAcceptedBy(a2, l, m.pid, m.val)}
            IN IF Majority(agreeing)
               THEN /\ finalPid' = [finalPid EXCEPT ![l] = m.pid]
                    /\ finalValue' = [finalValue EXCEPT ![l] = m.val]
                    /\ UNCHANGED <<msgs, proposalId, proposedVal, promisesRcvd, lastAcceptedId, promisedId, acceptedId, acceptedVal>>
               ELSE UNCHANGED vars

Next ==
    \/ (\E p \in Proposers : Prepare(p))
    \/ (\E a \in Acceptors, m \in msgs : HandlePrepare(a, m))
    \/ (\E p \in Proposers, m \in msgs : HandlePromise(p, m))
    \/ (\E a \in Acceptors, m \in msgs : HandleAccept(a, m))
    \/ (\E l \in Learners, m \in msgs : HandleAccepted(l, m))

Spec == Init /\ [][Next]_vars

====