---- MODULE EssentialPaxos ----
EXTENDS Naturals, FiniteSets, TLC

CONSTANTS Acceptors, Proposers, Learners, Values

ASSUME /\ Acceptors # {}
       /\ Proposers # {}
       /\ Learners # {}
       /\ Values # {}
       /\ IsFiniteSet(Acceptors)
       /\ IsFiniteSet(Proposers)
       /\ IsFiniteSet(Learners)
       /\ IsFiniteSet(Values)

Quorums == {Q \in SUBSET Acceptors : Cardinality(Q) * 2 > Cardinality(Acceptors)}

ProposalIDs == Nat \X Proposers

VARIABLES
    \* Proposer state
    proposerProposedValue,
    proposerProposalId,
    proposerLastAcceptedId,
    proposerNextProposalNumber,
    proposerPromisesRcvd,
    
    \* Acceptor state
    acceptorPromisedId,
    acceptorAcceptedId,
    acceptorAcceptedValue,
    
    \* Learner state
    learnerProposals,
    learnerAcceptors,
    learnerFinalValue,
    learnerFinalProposalId,
    
    \* Network
    msgs

vars == <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId,
          proposerNextProposalNumber, proposerPromisesRcvd,
          acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue,
          learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId,
          msgs>>

TypeOK ==
    /\ proposerProposedValue \in [Proposers -> Values \cup {CHOOSE x : x \notin Values}]
    /\ proposerProposalId \in [Proposers -> ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs}]
    /\ proposerLastAcceptedId \in [Proposers -> ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs}]
    /\ proposerNextProposalNumber \in [Proposers -> Nat]
    /\ proposerPromisesRcvd \in [Proposers -> SUBSET Acceptors \cup {CHOOSE x : x \notin SUBSET Acceptors}]
    /\ acceptorPromisedId \in [Acceptors -> ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs}]
    /\ acceptorAcceptedId \in [Acceptors -> ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs}]
    /\ acceptorAcceptedValue \in [Acceptors -> Values \cup {CHOOSE x : x \notin Values}]
    /\ learnerProposals \in [Learners -> [ProposalIDs -> Nat \X Nat \X Values] \cup {CHOOSE x : x \notin [ProposalIDs -> Nat \X Nat \X Values]}]
    /\ learnerAcceptors \in [Learners -> [Acceptors -> ProposalIDs] \cup {CHOOSE x : x \notin [Acceptors -> ProposalIDs]}]
    /\ learnerFinalValue \in [Learners -> Values \cup {CHOOSE x : x \notin Values}]
    /\ learnerFinalProposalId \in [Learners -> ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs}]
    /\ msgs \subseteq [type: {"Prepare", "Promise", "Accept", "Accepted"},
                       proposalId: ProposalIDs,
                       proposerUid: Proposers,
                       acceptorUid: Acceptors,
                       prevAcceptedId: ProposalIDs \cup {CHOOSE x : x \notin ProposalIDs},
                       prevAcceptedValue: Values \cup {CHOOSE x : x \notin Values},
                       value: Values]

NULL == CHOOSE x : x \notin (ProposalIDs \cup Values \cup SUBSET Acceptors \cup [ProposalIDs -> Nat \X Nat \X Values] \cup [Acceptors -> ProposalIDs])

Init ==
    /\ proposerProposedValue = [p \in Proposers |-> NULL]
    /\ proposerProposalId = [p \in Proposers |-> NULL]
    /\ proposerLastAcceptedId = [p \in Proposers |-> NULL]
    /\ proposerNextProposalNumber = [p \in Proposers |-> 1]
    /\ proposerPromisesRcvd = [p \in Proposers |-> NULL]
    /\ acceptorPromisedId = [a \in Acceptors |-> NULL]
    /\ acceptorAcceptedId = [a \in Acceptors |-> NULL]
    /\ acceptorAcceptedValue = [a \in Acceptors |-> NULL]
    /\ learnerProposals = [l \in Learners |-> NULL]
    /\ learnerAcceptors = [l \in Learners |-> NULL]
    /\ learnerFinalValue = [l \in Learners |-> NULL]
    /\ learnerFinalProposalId = [l \in Learners |-> NULL]
    /\ msgs = {}

Prepare(p) ==
    /\ proposerPromisesRcvd' = [proposerPromisesRcvd EXCEPT ![p] = {}]
    /\ proposerProposalId' = [proposerProposalId EXCEPT ![p] = <<proposerNextProposalNumber[p], p>>]
    /\ proposerNextProposalNumber' = [proposerNextProposalNumber EXCEPT ![p] = proposerNextProposalNumber[p] + 1]
    /\ msgs' = msgs \cup {[type |-> "Prepare", proposalId |-> <<proposerNextProposalNumber[p], p>>]}
    /\ UNCHANGED <<proposerProposedValue, proposerLastAcceptedId,
                   acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue,
                   learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandlePrepare(a, m) ==
    /\ m \in msgs
    /\ m.type = "Prepare"
    /\ \/ /\ m.proposalId = acceptorPromisedId[a]
          /\ msgs' = msgs \cup {[type |-> "Promise", 
                                 proposerUid |-> m.proposalId[2],
                                 proposalId |-> m.proposalId,
                                 prevAcceptedId |-> acceptorAcceptedId[a],
                                 prevAcceptedValue |-> acceptorAcceptedValue[a]]}
          /\ UNCHANGED <<acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue>>
       \/ /\ acceptorPromisedId[a] = NULL \/ m.proposalId[1] > acceptorPromisedId[a][1] \/ (m.proposalId[1] = acceptorPromisedId[a][1] /\ m.proposalId[2] > acceptorPromisedId[a][2])
          /\ acceptorPromisedId' = [acceptorPromisedId EXCEPT ![a] = m.proposalId]
          /\ msgs' = msgs \cup {[type |-> "Promise",
                                 proposerUid |-> m.proposalId[2],
                                 proposalId |-> m.proposalId,
                                 prevAcceptedId |-> acceptorAcceptedId[a],
                                 prevAcceptedValue |-> acceptorAcceptedValue[a]]}
          /\ UNCHANGED <<acceptorAcceptedId, acceptorAcceptedValue>>
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId,
                   proposerNextProposalNumber, proposerPromisesRcvd,
                   learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandlePromise(p, m) ==
    /\ m \in msgs
    /\ m.type = "Promise"
    /\ m.proposerUid = p
    /\ m.proposalId = proposerProposalId[p]
    /\ proposerPromisesRcvd[p] # NULL
    /\ \E a \in Acceptors : m.prevAcceptedId = acceptorAcceptedId[a] /\ m.prevAcceptedValue = acceptorAcceptedValue[a]
    /\ \E a \in Acceptors : a \notin proposerPromisesRcvd[p]
    /\ LET a == CHOOSE a \in Acceptors : m.prevAcceptedId = acceptorAcceptedId[a] /\ m.prevAcceptedValue = acceptorAcceptedValue[a] /\ a \notin proposerPromisesRcvd[p]
       IN /\ proposerPromisesRcvd' = [proposerPromisesRcvd EXCEPT ![p] = proposerPromisesRcvd[p] \cup {a}]
          /\ IF m.prevAcceptedId # NULL /\ (proposerLastAcceptedId[p] = NULL \/ m.prevAcceptedId[1] > proposerLastAcceptedId[p][1] \/ (m.prevAcceptedId[1] = proposerLastAcceptedId[p][1] /\ m.prevAcceptedId[2] > proposerLastAcceptedId[p][2]))
             THEN /\ proposerLastAcceptedId' = [proposerLastAcceptedId EXCEPT ![p] = m.prevAcceptedId]
                  /\ IF m.prevAcceptedValue # NULL
                     THEN proposerProposedValue' = [proposerProposedValue EXCEPT ![p] = m.prevAcceptedValue]
                     ELSE UNCHANGED proposerProposedValue
             ELSE UNCHANGED <<proposerLastAcceptedId, proposerProposedValue>>
          /\ IF Cardinality(proposerPromisesRcvd[p] \cup {a}) = CHOOSE n \in Nat : \E Q \in Quorums : Cardinality(Q) = n
             THEN IF proposerProposedValue'[p] # NULL
                  THEN msgs' = msgs \cup {[type |-> "Accept", proposalId |-> proposerProposalId[p], value |-> proposerProposedValue'[p]]}
                  ELSE UNCHANGED msgs
             ELSE UNCHANGED msgs
    /\ UNCHANGED <<proposerProposalId, proposerNextProposalNumber,
                   acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue,
                   learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandleAccept(a, m) ==
    /\ m \in msgs
    /\ m.type = "Accept"
    /\ acceptorPromisedId[a] = NULL \/ m.proposalId[1] > acceptorPromisedId[a][1] \/ (m.proposalId[1] = acceptorPromisedId[a][1] /\ m.proposalId[2] >= acceptorPromisedId[a][2])
    /\ acceptorPromisedId' = [acceptorPromisedId EXCEPT ![a] = m.proposalId]
    /\ acceptorAcceptedId' = [acceptorAcceptedId EXCEPT ![a] = m.proposalId]
    /\ acceptorAcceptedValue' = [acceptorAcceptedValue EXCEPT ![a] = m.value]
    /\ msgs' = msgs \cup {[type |-> "Accepted", proposalId |-> m.proposalId, value |-> m.value]}
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId,
                   proposerNextProposalNumber, proposerPromisesRcvd,
                   learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>

HandleAccepted(l, m) ==
    /\ m \in msgs
    /\ m.type = "Accepted"
    /\ learnerFinalValue[l] = NULL
    /\ \E a \in Acceptors : acceptorAcceptedId[a] = m.proposalId /\ acceptorAcceptedValue[a] = m.value
    /\ LET a == CHOOSE a \in Acceptors : acceptorAcceptedId[a] = m.proposalId /\ acceptorAcceptedValue[a] = m.value
       IN /\ IF learnerProposals[l] = NULL
             THEN /\ learnerProposals' = [learnerProposals EXCEPT ![l] = [pid \in {m.proposalId} |-> <<1, 1, m.value>>]]
                  /\ learnerAcceptors' = [learnerAcceptors EXCEPT ![l] = [aid \in {a} |-> m.proposalId]]
             ELSE /\ LET lastPn == IF a \in DOMAIN learnerAcceptors[l] THEN learnerAcceptors[l][a] ELSE NULL
                     IN IF lastPn = NULL \/ m.proposalId[1] > lastPn[1] \/ (m.proposalId[1] = lastPn[1] /\ m.proposalId[2] > lastPn[2])
                        THEN /\ learnerAcceptors' = [learnerAcceptors EXCEPT ![l] = learnerAcceptors[l] @@ (a :> m.proposalId)]
                             /\ LET newProposals == IF lastPn # NULL /\ lastPn \in DOMAIN learnerProposals[l]
                                                     THEN LET oldp == learnerProposals[l][lastPn]
                                                              newRetainCount == oldp[2] - 1
                                                          IN IF newRetainCount = 0
                                                             THEN [pid \in (DOMAIN learnerProposals[l] \ {lastPn}) |-> learnerProposals[l][pid]]
                                                             ELSE learnerProposals[l] @@ (lastPn :> <<oldp[1], newRetainCount, oldp[3]>>)
                                                     ELSE learnerProposals[l]
                                                currentEntry == IF m.proposalId \in DOMAIN newProposals THEN newProposals[m.proposalId] ELSE <<0, 0, m.value>>
                                                updatedEntry == <<currentEntry[1] + 1, currentEntry[2] + 1, m.value>>
                                            IN /\ learnerProposals' = [learnerProposals EXCEPT ![l] = newProposals @@ (m.proposalId :> updatedEntry)]
                                               /\ IF updatedEntry[1] = CHOOSE n \in Nat : \E Q \in Quorums : Cardinality(Q) = n
                                                  THEN /\ learnerFinalValue' = [learnerFinalValue EXCEPT ![l] = m.value]
                                                       /\ learnerFinalProposalId' = [learnerFinalProposalId EXCEPT ![l] = m.proposalId]
                                                       /\ learnerProposals' = [learnerProposals' EXCEPT ![l] = NULL]
                                                       /\ learnerAcceptors' = [learnerAcceptors' EXCEPT ![l] = NULL]
                                                  ELSE UNCHANGED <<learnerFinalValue, learnerFinalProposalId>>
                        ELSE UNCHANGED <<learnerProposals, learnerAcceptors, learnerFinalValue, learnerFinalProposalId>>
    /\ UNCHANGED <<proposerProposedValue, proposerProposalId, proposerLastAcceptedId,
                   proposerNextProposalNumber, proposerPromisesRcvd,
                   acceptorPromisedId, acceptorAcceptedId, acceptorAcceptedValue, msgs>>

Next ==
    \/ \E p \in Proposers : Prepare(p)
    \/ \E a \in Acceptors, m \in msgs : HandlePrepare(a, m)
    \/ \E p \in Proposers, m \in msgs : HandlePromise(p, m)
    \/ \E a \in Acceptors, m \in msgs : HandleAccept(a, m)
    \/ \E l \in Learners, m \in msgs : HandleAccepted(l, m)

Spec == Init /\ [][Next]_vars

====