CREATE DATABASE IF NOT EXISTS `koala_db`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `koala_db`;

CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `email` VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
    `password_hash` VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
    `nickname` VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `activity_categories` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `code` VARCHAR(30) COLLATE utf8mb4_unicode_ci NOT NULL,
    `name` VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
    `is_active` TINYINT(1) NOT NULL DEFAULT '1',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_preferences` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `space_preference` VARCHAR(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `transport_mode` VARCHAR(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `user_id` (`user_id`),
    CONSTRAINT `fk_user_preferences_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_activity_preferences` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT UNSIGNED NOT NULL,
    `activity_id` BIGINT UNSIGNED NOT NULL,
    `preference_level` TINYINT UNSIGNED NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_user_activity` (`user_id`, `activity_id`),
    KEY `fk_user_activity_preferences_activity` (`activity_id`),
    CONSTRAINT `fk_user_activity_preferences_activity`
        FOREIGN KEY (`activity_id`) REFERENCES `activity_categories` (`id`) ON DELETE RESTRICT,
    CONSTRAINT `fk_user_activity_preferences_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `chk_preference_level`
        CHECK (`preference_level` BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `activity_categories` (`code`, `name`, `is_active`)
VALUES
    ('food', '음식', 1),
    ('cafe', '카페', 1),
    ('walk', '산책', 1),
    ('culture', '문화', 1),
    ('entertainment', '놀거리', 1),
    ('shopping', '쇼핑', 1),
    ('drink', '술', 1)
ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `is_active` = VALUES(`is_active`);
