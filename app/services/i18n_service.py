from typing import Any

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": "Welcome to PharmaGo",
        "delivery_assigned": "Delivery assigned successfully",
        "prescription_created": "Prescription created successfully",
        "payment_pending": "Payment pending",
        "payment_completed": "Payment completed",
        "payment_failed": "Payment failed",
        "invalid_credentials": "Invalid username or password",
        "not_found": "Resource not found",
        "forbidden": "Access denied",
        "server_error": "Internal server error",
        "rate_limited": "Too many requests, please try again later",
        "password_weak": "Password does not meet security requirements",
        "email_invalid": "Invalid email format",
        "otp_sent": "OTP has been sent to your phone",
        "delivery_in_transit": "Your delivery is on the way",
        "delivery_delivered": "Your package has been delivered",
    },
    "fr": {
        "welcome": "Bienvenue sur PharmaGo",
        "delivery_assigned": "Livraison assignée avec succès",
        "prescription_created": "Ordonnance créée avec succès",
        "payment_pending": "Paiement en attente",
        "payment_completed": "Paiement effectué",
        "payment_failed": "Paiement échoué",
        "invalid_credentials": "Nom d'utilisateur ou mot de passe incorrect",
        "not_found": "Ressource non trouvée",
        "forbidden": "Accès refusé",
        "server_error": "Erreur interne du serveur",
        "rate_limited": "Trop de requêtes, veuillez réessayer plus tard",
        "password_weak": "Le mot de passe ne respecte pas les exigences de sécurité",
        "email_invalid": "Format d'email invalide",
        "otp_sent": "OTP envoyé sur votre téléphone",
        "delivery_in_transit": "Votre livraison est en route",
        "delivery_delivered": "Votre colis a été livré",
    },
    "ar": {
        "welcome": "مرحباً بك في فارماغو",
        "delivery_assigned": "تم تعيين التوصيل بنجاح",
        "prescription_created": "تم إنشاء الوصفة الطبية بنجاح",
        "payment_pending": "الدفع معلق",
        "payment_completed": "تم الدفع",
        "payment_failed": "فشل الدفع",
        "invalid_credentials": "اسم المستخدم أو كلمة المرور غير صحيحة",
        "not_found": "الموارد غير موجودة",
        "forbidden": "تم رفض الوصول",
        "server_error": "خطأ داخلي في الخادم",
        "rate_limited": "طلبات كثيرة جداً، يرجى المحاولة لاحقاً",
        "password_weak": "كلمة المرور لا تستوفي متطلبات الأمان",
        "email_invalid": "تنسيق البريد الإلكتروني غير صالح",
        "otp_sent": "تم إرسال رمز التحقق إلى هاتفك",
        "delivery_in_transit": "توصيلك في الطريق",
        "delivery_delivered": "تم توصيل الطرد الخاص بك",
    },
}

SUPPORTED_LOCALES = list(TRANSLATIONS.keys())


def t(key: str, locale: str = "en") -> str:
    return TRANSLATIONS.get(locale, TRANSLATIONS["en"]).get(key, key)


def get_translations(locale: str) -> dict[str, str]:
    return TRANSLATIONS.get(locale, TRANSLATIONS["en"])


from fastapi import Request


def get_locale(request: Request) -> str:
    lang = request.headers.get("accept-language", "en")[:2].lower()
    return lang if lang in SUPPORTED_LOCALES else "en"
