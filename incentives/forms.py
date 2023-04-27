from django import forms


class SubnetForm(forms.Form):
    # Bittensor subnet IDs (netuid) are unsigned 16-bit integers.
    subnet = forms.IntegerField(
        label="Subnet UID",
        min_value=0,
        max_value=65535,
        error_messages={"required": "Enter a subnet number.", "invalid": "Enter a whole number, such as 18."},
    )
