from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import IntegerField, Case, When, Value
from django.db.models.aggregates import Count
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.html import format_html, urlencode
from django.urls import reverse
from . import models


admin.site.register(models.ListedItemOffer)
admin.site.register(models.PaymentEmailContent)


@admin.action(description='Start selected campaigns')
def start_campaigns(modeladmin, request, queryset):
    for campaign in queryset:
        if campaign.posh_user and campaign.posh_user.is_active_in_posh:
            campaign_listings = models.Listing.objects.filter(campaign__id=campaign.id)
            items_to_list = []

            for campaign_listing in campaign_listings:
                try:
                    listed_item = models.ListedItem.objects.get(posh_user=campaign.posh_user, listing=campaign_listing)
                    if listed_item.status == models.ListedItem.NOT_LISTED:
                        items_to_list.append(campaign_listing)

                except models.ListedItem.DoesNotExist:
                    item_to_list = models.ListedItem(posh_user=campaign.posh_user, listing=campaign_listing,
                                              listing_title=campaign_listing.title)
                    item_to_list.save()
                    items_to_list.append(item_to_list)
                except models.ListedItem.MultipleObjectsReturned as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(e, exc_info=True)

            campaign.status = models.Campaign.STARTING
            campaign.next_runtime = timezone.now()
            campaign.queue_status = 'CALCULATING'
            campaign.save(update_fields=['status', 'next_runtime', 'queue_status'])


@admin.action(description='Stop selected campaigns')
def stop_campaigns(modeladmin, request, queryset):
    queryset.update(status=models.Campaign.STOPPING, next_runtime=None)


@admin.action(description='Disable posh user')
def disable_posh_users(modeladmin, request, queryset):
    queryset.update(is_active=False, date_disabled=timezone.now())


@admin.action(description='Enable posh user')
def enable_posh_users(modeladmin, request, queryset):
    queryset.update(is_active=True, date_disabled=None)


@admin.action(description='Check device in')
def check_devices_in(modeladmin, request, queryset):
    queryset.update(checked_out_by=None, checkout_time=None)


@admin.action(description='Check proxy in')
def check_proxies_in(modeladmin, request, queryset):
    queryset.update(checked_out_by=None, checkout_time=None)


class ListingInline(admin.StackedInline):
    model = models.Listing
    extra = 0


class ListingImageInline(admin.TabularInline):
    model = models.ListingImage
    extra = 0


class LogEntryInline(admin.StackedInline):
    model = models.LogEntry
    extra = 0
    fields = ['level', 'timestamp_seconds', 'message', 'image']
    readonly_fields = ['level', 'timestamp_seconds', 'message', 'image']
    ordering = ['timestamp']

    @staticmethod
    def timestamp_seconds(log_entry):
        return log_entry.timestamp.strftime('%b %d, %Y, %I:%M:%S %p')


class PoshUserStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return (
            ('unassigned', 'Unassigned'),
            ('assigned', 'Assigned'),
            ('running', 'Running'),
            ('disabled', 'Disabled'),
        )

    def queryset(self, request, queryset):
        value = self.value()

        if value == 'unassigned':
            return queryset.filter(campaign__isnull=True)
        elif value == 'assigned':
            return queryset.filter(campaign__status=models.Campaign.IDLE)
        elif value == 'running':
            return queryset.filter(campaign__status=models.Campaign.RUNNING)
        elif value == 'disabled':
            return queryset.filter(is_active=False)

        return queryset


@admin.register(models.ListedItemReport)
class ListedItemReportAdmin(admin.ModelAdmin):
    list_display = ['posh_user', 'associated_listed_item_to_report', 'report_type', 'datetime_reported']

    @admin.display(ordering='listed_item_to_report')
    def associated_listed_item_to_report(self, listed_item_report: models.ListedItemReport):
        url = f"{reverse('admin:core_listeditemtoreport_changelist')}?{urlencode({'id': str(listed_item_report.listed_item_to_report.id)})}"
        return format_html('<a href="{}">{}</a>', url, listed_item_report.listed_item_to_report.listing_title)

    @admin.display(ordering='listed_item_to_report__report_type')
    def report_type(self, obj):
        return obj.listed_item_to_report.report_type


@admin.register(models.ListedItemToReport)
class ListedItemToReportAdmin(admin.ModelAdmin):
    list_display = ['listing_title', 'report_type', 'item_url']
    search_fields = ['listing_title']

    @admin.display(ordering='listed_item_id')
    def item_url(self, listed_item_to_report: models.ListedItemToReport):
        if listed_item_to_report.listed_item_id:
            url = f'https://www.poshmark.com/listing/{listed_item_to_report.listed_item_id}'
            return format_html(f'<a target="_blank" href="{url}">{listed_item_to_report.listing_title}</a>')


@admin.register(models.BadPhrase)
class BadPhraseAdmin(admin.ModelAdmin):
    list_display = ['phrase', 'report_type']


@admin.register(models.Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['serial', 'is_active', 'associated_campaign', 'checkout_time']
    readonly_fields = ['checked_out_by', 'checkout_time']
    actions = [check_devices_in]

    @admin.display(ordering='associated_campaign')
    def associated_campaign(self, device):
        campaign = models.Campaign.objects.get(id=device.checked_out_by)
        url = f"{reverse('admin:core_campaign_changelist')}?{urlencode({'id': str(campaign.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.title)


@admin.register(models.Proxy)
class ProxyAdmin(admin.ModelAdmin):
    list_display = ['license_id', 'is_active', 'associated_campaign', 'checkout_time']
    readonly_fields = ['checked_out_by', 'checkout_time']
    actions = [check_proxies_in]

    @admin.display(ordering='associated_campaign')
    def associated_campaign(self, proxy):
        campaign = models.Campaign.objects.get(id=proxy.checked_out_by)
        url = f"{reverse('admin:core_campaign_changelist')}?{urlencode({'id': str(campaign.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.title)


@admin.register(models.User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (
            None,
            {
                'fields': ('username', 'password', 'email', 'first_name', 'last_name', 'phone_number'),
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('username', 'password1', 'password2', 'email', 'first_name', 'last_name', 'phone_number'),
            },
        ),
    )


@admin.register(models.PoshUser)
class PoshUserAdmin(admin.ModelAdmin):
    readonly_fields = ['date_added', 'time_to_install_clone', 'time_to_register', 'time_to_finish_registration', 'is_active', 'date_disabled', 'device']
    list_display = ['username', 'status', 'associated_user', 'associated_campaign', 'email', 'closet_url']
    search_fields = ['username__istartswith', 'email__istartswith']
    list_filter = ['user', PoshUserStatusFilter]
    list_per_page = 20

    def get_queryset(self, request):
        return super(PoshUserAdmin, self).get_queryset(request).select_related('campaign')

    @admin.display(ordering='campaign')
    def associated_campaign(self, posh_user):
        if posh_user.campaign:
            url = f"{reverse('admin:core_campaign_change', args=[posh_user.campaign.id])}"
            return format_html('<a href="{}">{}</a>', url, posh_user.campaign)
        return posh_user.campaign

    @admin.display(ordering='user')
    def associated_user(self, posh_user):
        url = f"{reverse('admin:core_user_change', args=[posh_user.user.id])}"
        return format_html('<a href="{}">{}</a>', url, posh_user.user)

    @admin.display(ordering='posh_user__username')
    def closet_url(self, posh_user: models.PoshUser):
        url = f'https://www.poshmark.com/closet/{posh_user.username}'
        return format_html(f'<a target="_blank" href="{url}">{posh_user.username}</a>')

    fieldsets = (
        ('Important Information', {
            'fields': (
                ('is_active', 'is_active_in_posh', 'clone_installed', 'is_registered', 'finished_registration', 'profile_updated', 'send_support_email'),
                ('time_to_install_clone', 'time_to_register', 'time_to_finish_registration'),
                ('user', 'device', 'app_package'),
                ('date_added', 'date_disabled'),
                ('username', 'password', 'email', 'email_password', 'email_imap_password'),
                ('phone_number',)
            )
        }),
        ('Other Information', {
            'classes': ('collapse',),
            'fields': (
                ('first_name', 'last_name'),
                ('date_of_birth', 'gender'),
                ('house_number', 'road', 'city', 'state', 'postcode', 'lat', 'long'),
                ('profile_picture', 'profile_picture_id'),
                ('header_picture')
            )
        }),
    )


@admin.register(models.Listing)
class ListingAdmin(admin.ModelAdmin):
    autocomplete_fields = ['campaign']
    list_display = ['title', 'associated_user', 'associated_campaign']
    search_fields = ['title__istartswith']
    list_filter = ['user', 'campaign']
    list_per_page = 20
    inlines = [ListingImageInline]

    def get_queryset(self, request):
        return super(ListingAdmin, self).get_queryset(request).select_related('campaign')

    @admin.display(ordering='campaign')
    def associated_campaign(self, listing):
        if listing.campaign:
            url = f"{reverse('admin:core_campaign_change', args=[listing.campaign.id])}"
            return format_html('<a href="{}">{}</a>', url, listing.campaign)
        return listing.campaign

    @admin.display(ordering='user')
    def associated_user(self, listing):
        if listing.user:
            url = f"{reverse('admin:core_user_change', args=[listing.user.id])}"
            return format_html('<a href="{}">{}</a>', url, listing.user)
        return listing.user

    fieldsets = (
        ('Listing Information', {
            'fields': (
                ('user', 'campaign'),
                ('title',),
                ('size', 'brand'),
                ('category', 'subcategory'),
                ('original_price', 'listing_price', 'lowest_price'),
                ('description',),
                ('cover_photo',),
            )
        }),
    )


@admin.register(models.Campaign)
class CampaignAdmin(admin.ModelAdmin):
    autocomplete_fields = ['posh_user']
    list_display = ['title', 'status', 'queue_status_num', 'associated_user', 'associated_posh_user', 'listings_count', 'latest_log']
    search_fields = ['title__istartswith', 'posh_user__username__istartswith']
    list_filter = ['status', 'user']
    inlines = [ListingInline]
    actions = [start_campaigns, stop_campaigns]

    def get_queryset(self, request):
        return super(CampaignAdmin, self).get_queryset(request).select_related('posh_user')\
            .prefetch_related('loggroup_set').\
            annotate(
            listings_count=Count('listings'),
            queue_status_num=Case(
                When(queue_status__regex=r'^\d+$', then=Cast('queue_status', IntegerField())), default=Value(9999), output_field=IntegerField()
            )
        ).order_by('queue_status_num')

    @admin.display(ordering='posh_user')
    def associated_posh_user(self, campaign):
        if campaign.posh_user:
            url = f"{reverse('admin:core_poshuser_change', args=[campaign.posh_user.id])}"
            return format_html('<a href="{}">{}</a>', url, campaign.posh_user)
        return campaign.posh_user

    @admin.display(ordering='user')
    def associated_user(self, campaign):
        url = f"{reverse('admin:core_user_change', args=[campaign.user.id])}"
        return format_html('<a href="{}">{}</a>', url, campaign.user)

    @admin.display(ordering='listings_count')
    def listings_count(self, campaign):
        url = f"{reverse('admin:core_listing_changelist')}?{urlencode({'campaign__id': str(campaign.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.listings_count)

    @admin.display()
    def latest_log(self, campaign):
        log = campaign.loggroup_set.filter(posh_user=campaign.posh_user).first()
        if log:
            url = f"{reverse('admin:core_loggroup_change', args=[log.id])}"
            return format_html('<a href="{}">{}</a>', url, log.created_date.strftime('%m-%d-%Y %I:%M:%S'))
        return log

    @admin.display(ordering='queue_status_num')
    def queue_status_num(self, campaign):
        if campaign.queue_status.isnumeric():
            return campaign.queue_status_num
        return campaign.queue_status

    fieldsets = (
        ('Campaign Information', {
            'fields': (
                ('auto_run', 'generate_users'),
                ('user',),
                ('status', 'queue_status', 'next_runtime'),
                ('posh_user',),
                ('mode',),
                ('title', 'delay', 'lowest_price'),
            )
        }),
    )


@admin.register(models.LogGroup)
class LogGroupAdmin(admin.ModelAdmin):
    list_display = ['created_date', 'campaign', 'posh_user', 'has_error']
    readonly_fields = ['campaign', 'posh_user', 'created_date', 'has_error']
    list_filter = ['has_error', 'created_date']
    search_fields = ['posh_user__username__istartswith']
    inlines = [LogEntryInline]

    def get_queryset(self, request):
        return super(LogGroupAdmin, self).get_queryset(request)

    fieldsets = (
        ('Log Information', {
            'fields': (
                ('created_date',),
                ('campaign', 'posh_user'),
            )
        }),
    )


@admin.register(models.ListedItem)
class ListedItemAdmin(admin.ModelAdmin):
    readonly_fields = ['time_to_list']
    autocomplete_fields = ['posh_user']
    list_display = ['listing_title', 'status', 'item_url', 'associated_user', 'associated_posh_user']
    search_fields = ['listing_title__istartswith', 'posh_user__username__istartswith']
    list_filter = ['status', 'posh_user__user']

    def get_queryset(self, request):
        return super(ListedItemAdmin, self).get_queryset(request).select_related('posh_user')

    @admin.display(ordering='posh_user')
    def associated_posh_user(self, listed_item):
        url = f"{reverse('admin:core_poshuser_change', args=[listed_item.posh_user.id])}"
        return format_html('<a href="{}">{}</a>', url, listed_item.posh_user)

    @admin.display(ordering='posh_user__user')
    def associated_user(self, listed_item):
        url = f"{reverse('admin:core_user_change', args=[listed_item.posh_user.user.id])}"
        return format_html('<a href="{}">{}</a>', url, listed_item.posh_user.user)

    @admin.display(ordering='listed_item_id')
    def item_url(self, listed_item: models.ListedItem):
        if listed_item.listed_item_id:
            url = f'https://www.poshmark.com/listing/{listed_item.listed_item_id}'
            return format_html(f'<a target="_blank" href="{url}">{listed_item.listing_title}</a>')

    fieldsets = (
        ('Campaign Information', {
            'fields': (
                ('posh_user', 'listing', 'earnings'),
                ('listing_title', 'listed_item_id', 'status', 'time_to_list'),
                ('datetime_listed', 'datetime_passed_review'),
                ('datetime_removed', 'datetime_sold', 'datetime_redeemable'),
            )
        }),
    )
