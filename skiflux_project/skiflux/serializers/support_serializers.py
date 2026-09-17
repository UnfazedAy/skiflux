from rest_framework import serializers

from skiflux.models.support import SupportTicket, TicketAttachment, TicketMessage


class TicketUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    username = serializers.CharField(allow_null=True)
    avatar_url = serializers.CharField(allow_null=True)


class TicketAdminSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    avatar_public_id = serializers.CharField(allow_null=True)


class SupportStatsSerializer(serializers.Serializer):
    open_tickets = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    resolved_today = serializers.IntegerField()
    unassigned = serializers.IntegerField()
    avg_response_minutes = serializers.FloatField(allow_null=True)
    satisfaction_rate = serializers.FloatField(allow_null=True)


class SupportAgentStatsSerializer(serializers.Serializer):
    total_assigned = serializers.IntegerField()
    open_tickets = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    resolved_today = serializers.IntegerField()
    total_resolved = serializers.IntegerField()
    avg_response_minutes = serializers.FloatField(allow_null=True)
    satisfaction_rate = serializers.FloatField(allow_null=True)


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = [
            "id",
            "file_url",
            "file_name",
            "file_size",
            "content_type",
            "created_at",
        ]


class TicketReplySerializer(serializers.Serializer):
    body = serializers.CharField(min_length=1)
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True,
        help_text="Optional file attachments.",
    )

    def validate_attachments(self, files):
        if not files:
            return []

        if isinstance(files, str):
            return []

        # ensure iterable safety
        if not hasattr(files, "__iter__"):
            raise serializers.ValidationError("Invalid attachments format.")

        max_size = 10 * 1024 * 1024  # 10MB per file
        allowed_types = [
            "image/jpeg",
            "image/png",
            "image/gif",
            "application/pdf",
            "text/plain",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]
        for file in files:
            if file.size > max_size:
                raise serializers.ValidationError(
                    f"{file.name} exceeds the 10MB limit."
                )
            if file.content_type not in allowed_types:
                raise serializers.ValidationError(
                    f"{file.name} has an unsupported file type."
                )
        return files


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_admin = TicketAdminSerializer(read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "direction",
            "sender_admin",
            "body",
            "attachments",
            "received_at",
            "created_at",
        ]


class SupportTicketListSerializer(serializers.ModelSerializer):
    assigned_to = TicketAdminSerializer(read_only=True)
    message_count = serializers.IntegerField(default=0)
    last_message_at = serializers.SerializerMethodField()
    sender_display = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "subject",
            "category",
            "status",
            "sender_email",
            "sender_name",
            "sender_display",
            "assigned_to",
            "message_count",
            "last_message_at",
            "created_at",
            "updated_at",
        ]

    def get_last_message_at(self, obj):
        last = obj.messages.order_by("-created_at").first()
        return last.created_at.isoformat() if last else None

    def get_sender_display(self, obj):
        if obj.user:
            return {
                "name": f"{obj.user.first_name} {obj.user.last_name}".strip(),
                "email": obj.user.email,
                "is_registered": True,
            }
        return {
            "name": obj.sender_name or obj.sender_email,
            "email": obj.sender_email,
            "is_registered": False,
        }


class SupportTicketDetailSerializer(serializers.ModelSerializer):
    user = TicketUserSerializer(read_only=True)
    assigned_to = TicketAdminSerializer(read_only=True)
    resolved_by = TicketAdminSerializer(read_only=True)
    messages = TicketMessageSerializer(many=True, read_only=True)
    sender_display = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "subject",
            "category",
            "status",
            "sender_email",
            "sender_name",
            "sender_display",
            "user",
            "assigned_to",
            "resolved_by",
            "resolved_at",
            "satisfaction_score",
            "messages",
            "created_at",
            "updated_at",
        ]

    def get_sender_display(self, obj):
        if obj.user:
            return {
                "name": f"{obj.user.first_name} {obj.user.last_name}".strip(),
                "email": obj.user.email,
                "is_registered": True,
            }
        return {
            "name": obj.sender_name or obj.sender_email,
            "email": obj.sender_email,
            "is_registered": False,
        }


class AssignableAdminSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    avatar_public_id = serializers.CharField(allow_null=True)
    role_type = serializers.CharField()


class AssignTicketSerializer(serializers.Serializer):
    admin_id = serializers.UUIDField()


class ResolveTicketSerializer(serializers.Serializer):
    # no body needed — action is self-contained
    pass


class ReopenTicketSerializer(serializers.Serializer):
    # no body needed — action is self-contained
    pass


class SatisfactionScoreSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=1, max_value=5)


class TicketFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=SupportTicket.Status.choices,
        required=False,
        allow_blank=True,
    )
    category = serializers.ChoiceField(
        choices=SupportTicket.Category.choices,
        required=False,
        allow_blank=True,
    )
    assigned_to_id = serializers.UUIDField(required=False)
    unassigned = serializers.BooleanField(required=False, default=False)
    search = serializers.CharField(required=False, allow_blank=True)
