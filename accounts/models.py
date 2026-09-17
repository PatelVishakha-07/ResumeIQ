import os
from django.db import models
from django.conf import settings

#User model 
class User(models.Model):
    role_choices = [
        ('user', 'User'),
        ('admin', 'Admin')
    ]

    user_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    email = models.EmailField( max_length=100, unique=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    role = models.CharField(max_length=10, choices=role_choices, default='user')
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    #forces the table name to be user instead of accounts_user
    class Meta:
        db_table = 'user'

    def __str__(self):
        return self.email


def profile_image_path(instance, filename):
    ext = filename.split('.')[-1]
    return f"profiles/user_{instance.user.user_id}.{ext}"

class Profile(models.Model):
    user = models.OneToOneField(
        'User',                     
        on_delete=models.CASCADE,
        related_name='profile',
        db_column='user_id'
    )
    profile_image = models.ImageField(
        upload_to=profile_image_path,
        null=True,
        blank=True
    )
    bio = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'profile'

    def get_image_url(self):
        if self.profile_image:
            return f"{self.profile_image.url}?v={self.updated_at.timestamp()}"

        return settings.STATIC_URL + 'img/default-avatar.png'