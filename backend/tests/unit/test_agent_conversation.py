from app.agent.conversation import ConversationStore


class TestConversationStore:
    def test_empty_history_for_a_new_conversation(self):
        store = ConversationStore()
        assert store.get_history(user_id="u1", conversation_id="c1") == []

    def test_appended_turns_are_retrievable_in_order(self):
        store = ConversationStore()
        store.append_turn(
            user_id="u1", conversation_id="c1", role="user", content="Tell me about AAPL."
        )
        store.append_turn(
            user_id="u1", conversation_id="c1", role="assistant", content="AAPL is..."
        )

        history = store.get_history(user_id="u1", conversation_id="c1")

        assert [(t.role, t.content) for t in history] == [
            ("user", "Tell me about AAPL."),
            ("assistant", "AAPL is..."),
        ]

    def test_history_is_bounded_to_max_turns(self):
        store = ConversationStore(max_turns=2)
        for i in range(5):
            store.append_turn(user_id="u1", conversation_id="c1", role="user", content=f"q{i}")
            store.append_turn(user_id="u1", conversation_id="c1", role="assistant", content=f"a{i}")

        history = store.get_history(user_id="u1", conversation_id="c1")

        assert len(history) == 4  # 2 turns = 4 messages
        assert [t.content for t in history] == ["q3", "a3", "q4", "a4"]  # most recent kept

    def test_different_conversations_for_the_same_user_are_isolated(self):
        store = ConversationStore()
        store.append_turn(user_id="u1", conversation_id="c1", role="user", content="about AAPL")
        store.append_turn(user_id="u1", conversation_id="c2", role="user", content="about MSFT")

        c1_history = store.get_history(user_id="u1", conversation_id="c1")
        c2_history = store.get_history(user_id="u1", conversation_id="c2")
        assert [t.content for t in c1_history] == ["about AAPL"]
        assert [t.content for t in c2_history] == ["about MSFT"]

    def test_same_conversation_id_for_different_users_is_isolated(self):
        """Critical for cross-user conversation leakage prevention: a
        conversation_id is not a global key, it's scoped per user."""
        store = ConversationStore()
        store.append_turn(
            user_id="user-a", conversation_id="shared-id", role="user", content="Alice's message"
        )
        store.append_turn(
            user_id="user-b", conversation_id="shared-id", role="user", content="Bob's message"
        )

        alice_history = store.get_history(user_id="user-a", conversation_id="shared-id")
        bob_history = store.get_history(user_id="user-b", conversation_id="shared-id")

        assert [t.content for t in alice_history] == ["Alice's message"]
        assert [t.content for t in bob_history] == ["Bob's message"]

    def test_new_conversation_id_generates_a_unique_value(self):
        store = ConversationStore()
        first = store.new_conversation_id()
        second = store.new_conversation_id()
        assert first != second
        assert isinstance(first, str) and len(first) > 0
