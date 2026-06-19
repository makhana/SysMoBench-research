---- MODULE EssentialPaxos ----
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Acceptors, Proposers, Learners, Values, NoValue, MaxBallot

ProposalIDs == (0..MaxBallot) \X Proposers

ProposalIDLt(a, b) == a[1] < b[1]

Quorums == {Q \in SUBSET Acceptors : Cardinality(Q) * 2 > Cardinality(Acceptors)}

VARIABLES
    proposerProposedValue,
    proposerProposalId,
    proposerLastAcceptedId,
    proposerNextProposalNumber,
    proposerPromisesRcvd,
    acceptorPromisedId,
    acceptorAcceptedId,
    acceptorAcceptedValue,
    learnerProposals,
    learnerAcceptors,
    learnerFinalValue,
    learnerFinalProposalId,
    msgs

vars == <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId, 
          proposerNextProposalNumber, proposerPromisesRcvd, acceptorPromisedId, 
          acceptorAcceptedId, acceptorAcceptedValue, learnerProposals, 
          learnerAcceptors, learnerFinalValue, learnerFinalProposalId, msgs>>

TypeOK ==
    /\ proposerProposedValue \in [Proposers -> Values \cup {NoValue}]
    /\ proposerProposalId \in [Proposers -> ProposalIDs \cup {NoValue}]
    /\ proposerLastAcceptedId \in [Proposers -> ProposalIDs \cup {NoValue}]
    /\ proposerNextProposalNumber \in [Proposers -> 0..MaxBallot+1]
    /\ proposerPromisesRcvd \in [Proposers -> SUBSET Acceptors]
    /\ acceptorPromisedId \in [Acceptors -> ProposalIDs \cup {NoValue}]
    /\ acceptorAcceptedId \in [Acceptors -> ProposalIDs \cup {NoValue}]
    /\ acceptorAcceptedValue \in [Acceptors -> Values \cup {NoValue}]
    /\ learnerProposals \in [Learners -> [ProposalIDs -> [accept_count: Nat, retain_count: Nat, value: Values] \cup {NoValue}] \cup {NoValue}]
    /\ learnerAcceptors \in [Learners -> [Acceptors -> ProposalIDs \cup {NoValue}] \cup {NoValue}]
    /\ learnerFinalValue \in [Learners -> Values \cup {NoValue}]
    /\ learnerFinalProposalId \in [Learners -> ProposalIDs \cup {NoValue}]
    /\ msgs \in SUBSET [type: {"prepare", "promise", "accept", "accepted"}, from: Proposers \cup Acceptors, to: Proposers \cup Acceptors \cup Learners, proposal_id: ProposalIDs, prev_accepted_id: ProposalIDs \cup {NoValue}, value: Values \cup {NoValue}]

Init ==
    /\ proposerProposedValue = [p \in Proposers |-> NoValue]
    /\ proposerProposalId = [p \in Proposers |-> NoValue]
    /\ proposerLastAcceptedId = [p \in Proposers |-> NoValue]
    /\ proposerNextProposalNumber = [p \in Proposers |-> 1]
    /\ proposerPromisesRcvd = [p \in Proposers |-> {}]
    /\ acceptorPromisedId = [a \in Acceptors |-> NoValue]
    /\ acceptorAcceptedId = [a \in Acceptors |-> NoValue]
    /\ acceptorAcceptedValue = [a \in Acceptors |-> NoValue]
    /\ learnerProposals = [l \in Learners |-> NoValue]
    /\ learnerAcceptors = [l \in Learners |-> NoValue]
    /\ learnerFinalValue = [l \in Learners |-> NoValue]
    /\ learnerFinalProposalId = [l \in Learners |-> NoValue]
    /\ msgs = {}

Prepare(p) ==
    /\ proposerNextProposalNumber[p] <= MaxBallot
    /\ proposerPromisesRcvd' = [proposerPromisesRcvd EXCEPT ![p] = {}]
    /\ proposerProposalId' = [proposerProposalId EXCEPT ![p] = <<proposerNextProposalNumber[p], p>>]
    /\ proposerNextProposalNumber' = [proposerNextProposalNumber EXCEPT ![p] = proposerNextProposalNumber[p] + 1]
    /\ msgs' = msgs \cup {[type |-> "prepare", from |-> p, to |-> a, proposal_id |-> <<proposerNextProposalNumber[p], p>>, prev_accepted_id |-> NoValue, value |-> NoValue] : a \in Acceptors}
    /\ UNCHANGED <<proposerProposedValue, proposerLastAcceptedId, acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue, learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandlePrepare(a) ==
    /\ \E m \in msgs :
        /\ m.type = "prepare"
        /\ m.to = a
        /\ \/ /\ m.proposal_id = acceptorPromisedId[a]
              /\ msgs' = msgs \cup {[type |-> "promise", from |-> a, to |-> m.from, proposal_id |-> m.proposal_id, prev_accepted_id |-> acceptorAcceptedId[a], value |-> acceptorAcceptedValue[a]]}
              /\ UNCHANGED <<acceptorPromisedId>>
           \/ /\ IF acceptorPromisedId[a] = NoValue THEN TRUE ELSE ProposalIDLt(acceptorPromisedId[a], m.proposal_id)
              /\ acceptorPromisedId' = [acceptorPromisedId EXCEPT ![a] = m.proposal_id]
              /\ msgs' = msgs \cup {[type |-> "promise", from |-> a, to |-> m.from, proposal_id |-> m.proposal_id, prev_accepted_id |-> acceptorAcceptedId[a], value |-> acceptorAcceptedValue[a]]}
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId, proposerNextProposalNumber, proposerPromisesRcvd, acceptorAcceptedId, acceptorAcceptedValue, learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandlePromise(p) ==
    /\ \E m \in msgs :
        /\ m.type = "promise"
        /\ m.to = p
        /\ m.proposal_id = proposerProposalId[p]
        /\ m.from \notin proposerPromisesRcvd[p]
        /\ proposerPromisesRcvd' = [proposerPromisesRcvd EXCEPT ![p] = proposerPromisesRcvd[p] \cup {m.from}]
        /\ IF m.prev_accepted_id # NoValue /\ (proposerLastAcceptedId[p] = NoValue \/ ProposalIDLt(proposerLastAcceptedId[p], m.prev_accepted_id))
           THEN /\ proposerLastAcceptedId' = [proposerLastAcceptedId EXCEPT ![p] = m.prev_accepted_id]
                /\ IF m.value # NoValue
                   THEN proposerProposedValue' = [proposerProposedValue EXCEPT ![p] = m.value]
                   ELSE UNCHANGED proposerProposedValue
           ELSE UNCHANGED <<proposerLastAcceptedId, proposerProposedValue>>
        /\ IF Cardinality(proposerPromisesRcvd[p] \cup {m.from}) * 2 > Cardinality(Acceptors) /\ proposerProposedValue'[p] # NoValue
           THEN msgs' = msgs \cup {[type |-> "accept", from |-> p, to |-> a, proposal_id |-> proposerProposalId[p], prev_accepted_id |-> NoValue, value |-> proposerProposedValue'[p]] : a \in Acceptors}
           ELSE msgs' = msgs
    /\ UNCHANGED <<proposerProposalId, proposerNextProposalNumber, acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue, learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandleAccept(a) ==
    /\ \E m \in msgs :
        /\ m.type = "accept"
        /\ m.to = a
        /\ IF acceptorPromisedId[a] = NoValue THEN TRUE ELSE ~ProposalIDLt(m.proposal_id, acceptorPromisedId[a])
        /\ acceptorPromisedId' = [acceptorPromisedId EXCEPT ![a] = m.proposal_id]
        /\ acceptorAcceptedId' = [acceptorAcceptedId EXCEPT ![a] = m.proposal_id]
        /\ acceptorAcceptedValue' = [acceptorAcceptedValue EXCEPT ![a] = m.value]
        /\ msgs' = msgs \cup {[type |-> "accepted", from |-> a, to |-> l, proposal_id |-> m.proposal_id, prev_accepted_id |-> NoValue, value |-> m.value] : l \in Learners}
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId, proposerNextProposalNumber, proposerPromisesRcvd, learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandleAccepted(l) ==
    /\ \E m \in msgs :
        /\ m.type = "accepted"
        /\ m.to = l
        /\ learnerFinalValue[l] = NoValue
        /\ LET proposals == IF learnerProposals[l] = NoValue THEN [pid \in ProposalIDs |-> NoValue] ELSE learnerProposals[l]
               acceptors == IF learnerAcceptors[l] = NoValue THEN [aid \in Acceptors |-> NoValue] ELSE learnerAcceptors[l]
               last_pn == acceptors[m.from]
           IN /\ IF last_pn = NoValue THEN TRUE ELSE ProposalIDLt(last_pn, m.proposal_id)
              /\ LET new_acceptors == [acceptors EXCEPT ![m.from] = m.proposal_id]
                     new_proposals == IF last_pn # NoValue /\ proposals[last_pn] # NoValue
                                      THEN LET old_entry == proposals[last_pn]
                                               updated_old == [old_entry EXCEPT !.retain_count = old_entry.retain_count - 1]
                                           IN IF updated_old.retain_count = 0
                                              THEN [pid \in ProposalIDs |-> IF pid = last_pn THEN NoValue ELSE proposals[pid]]
                                              ELSE [proposals EXCEPT ![last_pn] = updated_old]
                                      ELSE proposals
                     current_entry == IF new_proposals[m.proposal_id] = NoValue
                                      THEN [accept_count |-> 0, retain_count |-> 0, value |-> m.value]
                                      ELSE new_proposals[m.proposal_id]
                     final_entry == [current_entry EXCEPT !.accept_count = current_entry.accept_count + 1,
                                                           !.retain_count = current_entry.retain_count + 1]
                     final_proposals == [new_proposals EXCEPT ![m.proposal_id] = final_entry]
                 IN /\ learnerAcceptors' = [learnerAcceptors EXCEPT ![l] = new_acceptors]
                    /\ IF final_entry.accept_count * 2 > Cardinality(Acceptors)
                       THEN /\ learnerFinalValue' = [learnerFinalValue EXCEPT ![l] = m.value]
                            /\ learnerFinalProposalId' = [learnerFinalProposalId EXCEPT ![l] = m.proposal_id]
                            /\ learnerProposals' = [learnerProposals EXCEPT ![l] = NoValue]
                       ELSE /\ learnerProposals' = [learnerProposals EXCEPT ![l] = final_proposals]
                            /\ UNCHANGED <<learnerFinalValue, learnerFinalProposalId>>
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId, proposerNextProposalNumber, proposerPromisesRcvd, acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue, msgs>>

Next ==
    \/ \E p \in Proposers : Prepare(p)
    \/ \E a \in Acceptors : HandlePrepare(a)
    \/ \E p \in Proposers : HandlePromise(p)
    \/ \E a \in Acceptors : HandleAccept(a)
    \/ \E l \in Learners : HandleAccepted(l)

Spec == Init /\ [][Next]_vars

====